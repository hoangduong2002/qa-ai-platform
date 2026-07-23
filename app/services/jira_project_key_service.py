from __future__ import annotations

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.services.jira_project_keys import normalize_jira_project_key


def extract_jira_project_key(issue: dict | None, issue_key: str = "") -> str | None:
    """Extract Jira's project key, preferring fields.project.key."""
    fields = (issue or {}).get("fields") or {}
    project = fields.get("project") or {}
    candidate = project.get("key")
    if candidate:
        try:
            return normalize_jira_project_key(str(candidate))
        except KnowledgeValidationError:
            return None

    fallback = str(issue_key or (issue or {}).get("key") or "").strip()
    if "-" not in fallback:
        return None
    try:
        return normalize_jira_project_key(fallback.split("-", 1)[0])
    except KnowledgeValidationError:
        return None
