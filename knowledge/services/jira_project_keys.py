from __future__ import annotations

import re
from collections.abc import Iterable

from knowledge.domain.errors import KnowledgeValidationError


JIRA_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")


def normalize_jira_project_key(value: str) -> str:
    """Normalize and validate one Jira project key."""
    normalized = str(value or "").strip().upper()
    if not normalized or not JIRA_PROJECT_KEY_RE.fullmatch(normalized):
        display_value = str(value or "").strip()
        raise KnowledgeValidationError(
            f'Invalid Jira project key "{display_value}".'
        )
    return normalized


def normalize_jira_project_keys(values: Iterable[str] | None) -> list[str]:
    """Normalize keys and remove duplicates while retaining first-seen order."""
    if values is None:
        return []
    source = [values] if isinstance(values, str) else values
    normalized: list[str] = []
    seen: set[str] = set()
    for value in source:
        key = normalize_jira_project_key(value)
        if key not in seen:
            normalized.append(key)
            seen.add(key)
    return normalized
