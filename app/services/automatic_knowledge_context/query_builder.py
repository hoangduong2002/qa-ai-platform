from __future__ import annotations

import re

from app.services.automatic_knowledge_context.config import (
    max_queries,
    max_query_characters,
)
from app.services.automatic_knowledge_context.models import KnowledgeQuery


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_WORDS = {
    "about", "after", "also", "and", "are", "been", "before", "being",
    "between", "description", "for", "from", "into", "jira", "must", "not",
    "requirement", "should", "that", "the", "their", "then", "this", "ticket",
    "use", "using", "when", "where", "with",
}


def _keywords(*values: str, limit: int = 10) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for match in _TOKEN_RE.findall(value or ""):
            normalized = match.upper() if any(char.isdigit() for char in match) else match.lower()
            if normalized.lower() in _STOP_WORDS or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            result.append(normalized)
            if len(result) >= limit:
                return result
    return result


def _safe_match_query(tokens: list[str]) -> str:
    parts: list[str] = []
    current_length = 0
    limit = max_query_characters()
    for token in tokens:
        clean = token.replace('"', "").strip()
        if not clean:
            continue
        part = f'"{clean}"'
        added_length = len(part) + (4 if parts else 0)
        if current_length + added_length > limit:
            break
        parts.append(part)
        current_length += added_length
    return " OR ".join(parts)


def build_retrieval_queries(
    *,
    ticket: dict,
    requirement_context: str,
    collection_roles: dict[str, list[str]] | None = None,
) -> list[KnowledgeQuery]:
    """Build deterministic, bounded queries from Jira and requirement content."""
    summary = str(ticket.get("summary") or "")
    issue_type = str(ticket.get("issue_type") or "")
    components = " ".join(str(item) for item in (ticket.get("components") or []))
    labels = " ".join(str(item) for item in (ticket.get("labels") or []))
    base = _keywords(summary, components, labels, requirement_context, limit=10)
    if not base:
        return []

    codes = [item for item in base if any(char.isdigit() for char in item)]
    plans = [
        ("business_rules", base[:8]),
        ("domain", [*codes[:4], *base[:5]]),
        (
            "technical",
            [*codes[:4], *_keywords(components, labels, requirement_context, limit=6)],
        ),
        ("test_coverage", [*codes[:4], *base[:5]]),
        ("historical_defects", [*codes[:4], *base[:5]]),
        ("project_guidelines", _keywords(issue_type, summary, limit=8)),
    ]
    roles = collection_roles or {}
    queries: list[KnowledgeQuery] = []
    seen: set[tuple[str, str | None]] = set()
    for category, tokens in plans:
        clean_tokens = list(dict.fromkeys(tokens))
        query = _safe_match_query(clean_tokens)
        if not query:
            continue
        collections = roles.get(category) or [None]
        for collection_id in collections[:1]:
            key = (query.lower(), collection_id)
            if key in seen:
                continue
            seen.add(key)
            queries.append(
                KnowledgeQuery(
                    category=category,
                    query=query,
                    collection_id=collection_id,
                )
            )
            if len(queries) >= max_queries():
                return queries
    return queries


def classify_collection_roles(collections) -> dict[str, list[str]]:
    """Compatibility adapter for collections that predate explicit role metadata."""
    roles: dict[str, list[str]] = {}
    for collection in sorted(collections, key=lambda item: (item.priority, item.collection_id)):
        text = " ".join(
            [
                collection.collection_id,
                collection.name,
                collection.description,
            ]
        ).lower()
        if "business" in text or "rule" in text:
            role = "business_rules"
        elif "defect" in text or "bug" in text:
            role = "historical_defects"
        elif "test" in text or "case" in text or "coverage" in text:
            role = "test_coverage"
        elif "guideline" in text or "profile" in text:
            role = "project_guidelines"
        elif "api" in text or "integration" in text or "technical" in text:
            role = "technical"
        else:
            role = "domain"
        roles.setdefault(role, []).append(collection.collection_id)
    return roles
