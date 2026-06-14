import json
import re
from pathlib import Path
from typing import Any


REQUIREMENTS_ROOT = Path("requirements")


def _requirement_root(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}

    return value if isinstance(value, dict) else {}


def _metadata(ticket_id: str) -> dict[str, Any]:
    return _read_json(_requirement_root(ticket_id) / "metadata.json")


def _ticket(ticket_id: str) -> dict[str, Any]:
    return _read_json(_requirement_root(ticket_id) / "ticket.json")


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _looks_like_jira_source(value: Any) -> bool:
    source = _normalize(value).lower()
    return source == "jira" or source.startswith("jira:")


def has_jira_snapshot(ticket_id: str) -> bool:
    root = _requirement_root(ticket_id)
    snapshots_dir = root / "snapshots"
    source_dir = root / "source"

    if (snapshots_dir / "latest_jira_snapshot.json").exists():
        return True

    if any(snapshots_dir.glob("jira_snapshot*.json")):
        return True

    if (source_dir / "jira_issue.json").exists():
        return True

    return any(source_dir.glob("jira_snapshot*.json"))


def get_jira_key(ticket_id: str) -> str | None:
    metadata = _metadata(ticket_id)
    ticket = _ticket(ticket_id)

    for source in (metadata, ticket):
        for key in ("jira_key", "issue_key"):
            value = _normalize(source.get(key))
            if value:
                return value.upper()

        source_value = _normalize(source.get("source"))
        if source_value.lower().startswith("jira:"):
            _, _, jira_key = source_value.partition(":")
            if jira_key.strip():
                return jira_key.strip().upper()

    jira_dir = _requirement_root(ticket_id) / "source" / "jira"
    if jira_dir.exists():
        for path in sorted(jira_dir.glob("*_raw.json")):
            match = re.match(r"(.+)_raw\.json$", path.name)
            if match:
                return match.group(1).upper()

    return None


def is_jira_requirement(ticket_id: str) -> bool:
    metadata = _metadata(ticket_id)
    ticket = _ticket(ticket_id)

    evidence_sources = (metadata, ticket)
    for source in evidence_sources:
        if _normalize(source.get("source_type")).lower() == "jira":
            return True

        if source.get("imported_from_jira") is True:
            return True

        if _looks_like_jira_source(source.get("source")):
            return True

        if _normalize(source.get("jira_key")):
            return True

    root = _requirement_root(ticket_id)
    if has_jira_snapshot(ticket_id):
        return True

    if (root / "source" / "jira_issue.json").exists():
        return True

    return (root / "source" / "jira_requirement.md").exists()


def get_requirement_source(ticket_id: str) -> str:
    if is_jira_requirement(ticket_id):
        return "jira"

    metadata = _metadata(ticket_id)
    ticket = _ticket(ticket_id)

    for source in (metadata, ticket):
        source_type = _normalize(source.get("source_type"))
        if source_type:
            return source_type.lower()

        source_value = _normalize(source.get("source"))
        if source_value:
            return source_value

    return "unknown"
