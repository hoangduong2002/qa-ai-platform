from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.quality_feedback.privacy import redact_payload
from app.services.quality_feedback.service import canonical_content_hash
from app.services.quality_feedback.versions import version_metadata
from evaluation.schemas.golden_dataset import GoldenDataset, GoldenTicket, load_dataset
from knowledge.storage.utils import atomic_write_json


def authorized_golden_reviewers() -> set[str]:
    raw = os.getenv("GOLDEN_DATASET_REVIEWER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _authorize(user: str) -> str:
    clean = " ".join((user or "").split())
    if not clean:
        raise PermissionError("Golden dataset changes require a reviewer identity.")
    if clean not in authorized_golden_reviewers():
        raise PermissionError(f"User {clean!r} is not authorized to approve golden data.")
    return clean


def _bump_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Dataset version must use semantic versioning: {version}")
    return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"


def _replace_ticket(value: Any, original: str, anonymized: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_ticket(item, original, anonymized) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ticket(item, original, anonymized) for item in value]
    if isinstance(value, str):
        return value.replace(original, anonymized)
    return value


def resolve_dataset_file(dataset_name: str, *, datasets_root: Path = Path("evaluation/datasets")) -> Path:
    root = datasets_root / dataset_name
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        current = str(manifest.get("current_dataset_path") or "").strip()
        if current:
            path = root / current
            if not path.exists():
                raise FileNotFoundError(f"Golden dataset manifest points to missing file: {path}")
            return path
    return root / "dataset.json"


def add_reviewed_ticket(
    *,
    dataset_name: str,
    ticket_id: str,
    expected_ticket: dict[str, Any],
    reviewed_by: str,
    change_reason: str,
    expectations_changed_reason: str = "",
    datasets_root: Path = Path("evaluation/datasets"),
    requirements_root: Path = Path("requirements"),
) -> dict[str, Any]:
    reviewer = _authorize(reviewed_by)
    reason = " ".join((change_reason or "").split())
    if not reason:
        raise ValueError("A reason for adding the reviewed ticket is required.")
    session_path = requirements_root / ticket_id / "testcases" / "testcase_session.json"
    try:
        session = json.loads(session_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError("The ticket must have a valid testcase review session.") from error
    if not session.get("approved"):
        raise ValueError("Only a QA-reviewed and approved ticket can enter the golden dataset.")

    dataset_path = resolve_dataset_file(dataset_name, datasets_root=datasets_root)
    dataset = load_dataset(dataset_path)
    root = datasets_root / dataset_name
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {
            "schema_version": "1.0",
            "dataset_id": dataset.dataset_id,
            "current_version": dataset.dataset_version,
            "current_dataset_path": str(dataset_path.relative_to(root)).replace("\\", "/"),
            "versions": [],
            "ticket_history": [],
        }
    )
    source_ticket_hash = hashlib.sha256(ticket_id.encode("utf-8")).hexdigest()
    prior = [
        item for item in manifest.get("ticket_history", [])
        if item.get("source_ticket_hash") == source_ticket_hash
    ]
    expectation_reason = " ".join((expectations_changed_reason or "").split())
    if prior and not expectation_reason:
        raise ValueError(
            "Changing existing golden expectations requires expectations_changed_reason."
        )

    anonymized_id = f"TICKET-{source_ticket_hash[:12].upper()}"
    payload = _replace_ticket(expected_ticket, ticket_id, anonymized_id)
    payload = redact_payload(payload)
    payload["ticket_id"] = anonymized_id
    new_version = _bump_patch(dataset.dataset_version)
    payload["dataset_version"] = new_version
    validated_ticket = GoldenTicket.model_validate(payload)

    tickets = [item for item in dataset.tickets if item.ticket_id != anonymized_id]
    tickets.append(validated_ticket)
    versioned_dataset = GoldenDataset(
        dataset_id=dataset.dataset_id,
        dataset_version=new_version,
        tickets=[item.model_copy(update={"dataset_version": new_version}) for item in tickets],
    )
    relative = Path("versions") / new_version / "dataset.json"
    version_path = root / relative
    if version_path.exists():
        raise FileExistsError(f"Golden dataset version already exists: {new_version}")
    atomic_write_json(version_path, versioned_dataset.model_dump(mode="json"))

    now = datetime.now().astimezone().isoformat()
    record = {
        "dataset_version": new_version,
        "dataset_path": str(relative).replace("\\", "/"),
        "approved_by": reviewer,
        "approved_at": now,
        "change_reason": reason,
        "expectations_changed_reason": expectation_reason or None,
        "source_ticket_hash": source_ticket_hash,
        "anonymized_ticket_id": anonymized_id,
        "expected_output_hash": canonical_content_hash(validated_ticket.model_dump(mode="json")),
        "versions": version_metadata(ticket_id, dataset_version=new_version).model_dump(mode="json"),
    }
    manifest.setdefault("versions", []).append(record)
    manifest.setdefault("ticket_history", []).append(record)
    manifest["current_version"] = new_version
    manifest["current_dataset_path"] = str(relative).replace("\\", "/")
    atomic_write_json(manifest_path, manifest)
    return record
