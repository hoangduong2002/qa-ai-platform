from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.automatic_knowledge_context.models import KnowledgeRetrievalSnapshot
from knowledge.storage.utils import atomic_write_json, validate_identifier


_SNAPSHOT_ID_RE = re.compile(r"^KS-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_analysis_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AR-{timestamp}-{uuid.uuid4().hex[:8]}"


def create_snapshot_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"KS-{timestamp}-{uuid.uuid4().hex[:8]}"


def _requirement_dir(ticket_id: str) -> Path:
    return Path("requirements") / validate_identifier(ticket_id, "ticket_id")


def _knowledge_dir(ticket_id: str) -> Path:
    return _requirement_dir(ticket_id) / "knowledge"


def save_snapshot(snapshot: KnowledgeRetrievalSnapshot) -> str:
    snapshots_dir = _knowledge_dir(snapshot.ticket_id) / "snapshots"
    path = snapshots_dir / f"{snapshot.snapshot_id}.json"
    payload = snapshot.model_dump(mode="json")
    atomic_write_json(path, payload)
    atomic_write_json(_knowledge_dir(snapshot.ticket_id) / "latest_snapshot.json", payload)
    return str(path)


def load_latest_snapshot(ticket_id: str) -> KnowledgeRetrievalSnapshot | None:
    path = _knowledge_dir(ticket_id) / "latest_snapshot.json"
    if not path.exists():
        return None
    return KnowledgeRetrievalSnapshot.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def load_snapshot(ticket_id: str, snapshot_id: str) -> KnowledgeRetrievalSnapshot:
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id or ""):
        raise ValueError("Invalid Knowledge Snapshot ID.")
    path = _knowledge_dir(ticket_id) / "snapshots" / f"{snapshot_id}.json"
    if not path.exists():
        raise FileNotFoundError("Knowledge Snapshot not found.")
    return KnowledgeRetrievalSnapshot.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def update_ticket_knowledge_metadata(snapshot: KnowledgeRetrievalSnapshot) -> None:
    path = _requirement_dir(snapshot.ticket_id) / "ticket.json"
    if not path.exists():
        return
    ticket = json.loads(path.read_text(encoding="utf-8"))
    ticket.update(
        {
            "jira_project_key": snapshot.jira_project_key,
            "knowledge_base_id": snapshot.knowledge_base_id,
            "knowledge_snapshot_id": snapshot.snapshot_id,
            "knowledge_retrieval_status": snapshot.status.value,
        }
    )
    atomic_write_json(path, ticket)


def save_analysis_run(
    *,
    ticket_id: str,
    analysis_run_id: str,
    snapshot_id: str,
    status: str,
    error: str | None = None,
) -> str:
    requirement_dir = _requirement_dir(ticket_id)
    analysis_path = requirement_dir / "analysis" / "requirement_analysis.json"
    analysis = {}
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0",
        "analysis_run_id": analysis_run_id,
        "ticket_id": ticket_id,
        "knowledge_snapshot_id": snapshot_id,
        "status": status,
        "created_at": utc_now_iso(),
        "analysis": analysis if status == "completed" else None,
        "error": error,
    }
    path = requirement_dir / "analysis" / "runs" / f"{analysis_run_id}.json"
    atomic_write_json(path, payload)
    atomic_write_json(requirement_dir / "analysis" / "latest_analysis_run.json", payload)
    return str(path)
