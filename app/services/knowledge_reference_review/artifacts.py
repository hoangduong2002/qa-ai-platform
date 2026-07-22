from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.knowledge_reference_review.models import ReviewedReference


def _knowledge_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "knowledge"


def _write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_candidate_references(ticket_id: str) -> list[dict]:
    return _read_json(_knowledge_dir(ticket_id) / "candidate_references.json", [])


def save_candidate_references(ticket_id: str, candidates: list[dict]) -> str:
    return _write_json(_knowledge_dir(ticket_id) / "candidate_references.json", candidates)


def read_review_requests(ticket_id: str) -> list[dict]:
    return _read_json(_knowledge_dir(ticket_id) / "review_requests.json", [])


def save_review_requests(ticket_id: str, requests: list[dict]) -> str:
    return _write_json(_knowledge_dir(ticket_id) / "review_requests.json", requests)


def read_review_records(ticket_id: str) -> list[dict]:
    return _read_json(_knowledge_dir(ticket_id) / "review_records.json", [])


def save_review_records(ticket_id: str, records: list[dict]) -> str:
    return _write_json(_knowledge_dir(ticket_id) / "review_records.json", records)


def save_selected_references(ticket_id: str, accepted: list[ReviewedReference]) -> str:
    return _write_json(
        _knowledge_dir(ticket_id) / "selected_references.json",
        [item.model_dump(mode="json") for item in accepted],
    )


def save_rejected_references(ticket_id: str, rejected: list[ReviewedReference]) -> str:
    return _write_json(
        _knowledge_dir(ticket_id) / "rejected_references.json",
        [item.model_dump(mode="json") for item in rejected],
    )


def save_conflicts(ticket_id: str, conflicts: list[dict]) -> str:
    return _write_json(_knowledge_dir(ticket_id) / "conflicts.json", conflicts)


def save_reference_context_markdown(ticket_id: str, accepted: list[ReviewedReference]) -> str:
    path = _knowledge_dir(ticket_id) / "reference_context.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Accepted Reference Context",
        "",
        "Only reviewed and ACCEPTED references are included.",
        "",
    ]

    if not accepted:
        lines.append("No accepted references.")
    else:
        for item in accepted:
            lines.extend(
                [
                    f"## {item.source_result_id}",
                    f"- Source: {item.kb_id}/{item.collection_id}/{item.document_id}",
                    f"- Version: {item.version}",
                    f"- Effective: {item.effective_from or 'N/A'} -> {item.effective_to or 'N/A'}",
                    f"- Confidence: {item.confidence}",
                    f"- Citation: {item.citation}",
                    f"- Intended Use: {item.intended_use}",
                    "- Excerpt:",
                    "",
                    f"> {item.excerpt}",
                    "",
                ]
            )

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def append_review_audit(ticket_id: str, event: dict) -> str:
    path = _knowledge_dir(ticket_id) / "review_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return str(path)
