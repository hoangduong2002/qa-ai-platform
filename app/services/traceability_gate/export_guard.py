from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.traceability_gate.config import (
    ExportQualityGateMode,
    authorized_qa_leads,
    blocking_rule_enabled,
    export_quality_gate_enabled,
    export_quality_gate_mode,
    traceability_gate_enabled,
)
from app.services.traceability_gate.models import (
    ExportBlocker,
    ExportDecisionV1,
    ExportGateStatus,
    ExportOverrideV1,
)
from app.services.traceability_gate.traceability import build_traceability
from knowledge.storage.utils import atomic_write_json, read_json


def _root(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id


def _read_json(path: Path, default):
    try:
        return read_json(path, default)
    except (OSError, json.JSONDecodeError):
        return default


def _unresolved_conflicts(ticket_id: str) -> list[dict]:
    rows = _read_json(_root(ticket_id) / "knowledge" / "conflicts.json", [])
    resolved = {"RESOLVED", "ACCEPTED", "REJECTED", "CLOSED"}
    return [
        item for item in rows
        if isinstance(item, dict)
        and item.get("resolved") is not True
        and str(item.get("status") or "OPEN").upper() not in resolved
        and item.get("human_confirmation_required", True) is not False
    ]


def _approval_status(ticket_id: str, version: str) -> dict:
    session = _read_json(
        _root(ticket_id) / "testcases" / "testcase_session.json",
        {},
    ) or {}
    approved = session.get("approved") is True
    approved_version = str(session.get("approved_version") or "")
    current_version = str(session.get("current_version") or "")
    if version == "approved":
        version_approved = approved and bool(approved_version)
    elif version == "latest":
        version_approved = approved and bool(approved_version) and approved_version == current_version
    else:
        version_approved = approved and approved_version == version
    return {
        "approved": version_approved,
        "selected_version": version,
        "approved_version": approved_version or None,
        "current_version": current_version or None,
    }


def _blocker(
    *,
    blocker_id: str,
    category: str,
    explanation: str,
    source: str,
    object_id: str | None = None,
) -> ExportBlocker:
    return ExportBlocker(
        blocker_id=blocker_id,
        category=category,
        explanation=explanation,
        source=source,
        object_id=object_id,
        configured_to_block=blocking_rule_enabled(category),
    )


def _trace_blockers(artifact) -> list[ExportBlocker]:
    result = []
    category_map = {
        "UNCOVERED_ACCEPTANCE_CRITERION": "UNCOVERED_ACCEPTANCE_CRITERION",
        "UNCOVERED_MANDATORY_COVERAGE": "UNCOVERED_MANDATORY_COVERAGE",
        "UNSUPPORTED_EXPECTED_RESULT": "UNSUPPORTED_EXPECTED_RESULT",
        "UNAPPROVED_KNOWLEDGE_REFERENCE": "UNSUPPORTED_EXPECTED_RESULT",
        "MISSING_TESTCASE_TRACEABILITY": "MISSING_TESTCASE_TRACEABILITY",
    }
    for issue in artifact.validation_issues:
        category = category_map.get(issue.category, issue.category)
        result.append(_blocker(
            blocker_id=issue.blocker_id,
            category=category,
            explanation=issue.explanation,
            source="traceability",
            object_id=issue.object_id,
        ))
    return result


def _quality_blockers(ticket_id: str) -> list[ExportBlocker]:
    report = _read_json(
        _root(ticket_id) / "test-design" / "test_quality_report.json",
        {},
    ) or {}
    result = []
    unsupported_categories = {
        "UNSUPPORTED_EXPECTED_RESULT", "INVENTED_AMOUNT", "INVENTED_STATUS",
        "INVENTED_MESSAGE", "INVENTED_CALCULATION", "MISSING_SOURCE_REFERENCE",
        "INVALID_SOURCE_REFERENCE", "UNRESOLVED_ASSUMPTION",
    }
    for issue in report.get("issues", []) if isinstance(report, dict) else []:
        if not isinstance(issue, dict) or str(issue.get("severity") or "") != "BLOCKER":
            continue
        issue_id = str(issue.get("issue_id") or "quality-blocker")
        original_category = str(issue.get("category") or "UNRESOLVED_BLOCKER")
        category = (
            "UNSUPPORTED_EXPECTED_RESULT"
            if original_category in unsupported_categories
            else "UNRESOLVED_BLOCKER"
        )
        result.append(_blocker(
            blocker_id=issue_id,
            category=category,
            explanation=str(issue.get("explanation") or "Unresolved quality blocker."),
            source="quality_report",
            object_id=issue.get("test_case_id"),
        ))
    return result


def _override_log(ticket_id: str) -> Path:
    return _root(ticket_id) / "audit" / "export_overrides.jsonl"


def _load_overrides(ticket_id: str) -> list[dict]:
    path = _override_log(ticket_id)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _matching_override(
    ticket_id: str,
    blocker_ids: set[str],
    scope: str,
) -> dict | None:
    if not blocker_ids:
        return None
    allowed = authorized_qa_leads()
    for item in reversed(_load_overrides(ticket_id)):
        if str(item.get("user_identity") or "") not in allowed:
            continue
        if str(item.get("scope") or "") not in {scope, "all_testcase_exports"}:
            continue
        affected = {str(value) for value in item.get("affected_blocker_ids", [])}
        if blocker_ids.issubset(affected):
            return item
    return None


def evaluate_export(
    *,
    ticket_id: str,
    testcases: list[dict],
    testcase_version: str,
    export_format: str,
    include_overrides: bool = True,
) -> ExportDecisionV1:
    trace_enabled = traceability_gate_enabled()
    gate_enabled = export_quality_gate_enabled()
    mode = export_quality_gate_mode() if gate_enabled else ExportQualityGateMode.WARN
    if not trace_enabled and not gate_enabled:
        return ExportDecisionV1(
            ticket_id=ticket_id,
            testcase_version=testcase_version,
            export_format=export_format,
            status=ExportGateStatus.ALLOWED,
            gate_enabled=False,
            gate_mode="off",
            approval_status={"approved": None, "gate_disabled": True},
        )

    traceability = build_traceability(
        ticket_id=ticket_id,
        testcases=testcases,
        selected_testcase_version=testcase_version,
        persist=trace_enabled,
    )
    candidates = _trace_blockers(traceability)
    candidates.extend(_quality_blockers(ticket_id))

    conflicts = _unresolved_conflicts(ticket_id)
    for index, conflict in enumerate(conflicts, start=1):
        conflict_id = str(conflict.get("conflict_id") or f"conflict-{index}")
        candidates.append(_blocker(
            blocker_id=f"CONFLICT-{conflict_id}",
            category="UNREVIEWED_CONFLICT",
            explanation=f"Conflict {conflict_id} still requires human review.",
            source="knowledge_conflicts",
            object_id=conflict_id,
        ))

    approval = _approval_status(ticket_id, testcase_version)
    if not approval["approved"]:
        candidates.append(_blocker(
            blocker_id=f"APPROVAL-{ticket_id}-{testcase_version}",
            category="MISSING_QA_APPROVAL",
            explanation=f"Test-case version {testcase_version} is not approved by QA.",
            source="testcase_session",
            object_id=testcase_version,
        ))

    unique = {item.blocker_id: item for item in candidates}
    candidates = list(unique.values())
    configured = [item for item in candidates if item.configured_to_block]
    actual_blockers = configured if gate_enabled and mode == ExportQualityGateMode.BLOCK else []
    warnings = [item for item in candidates if item not in actual_blockers]

    scope = f"{export_format}:{testcase_version}"
    override = (
        _matching_override(ticket_id, {item.blocker_id for item in actual_blockers}, scope)
        if include_overrides else None
    )
    if actual_blockers and override:
        status = ExportGateStatus.OVERRIDDEN
    elif actual_blockers:
        status = ExportGateStatus.BLOCKED
    elif candidates:
        status = ExportGateStatus.ALLOWED_WITH_WARNINGS
    else:
        status = ExportGateStatus.ALLOWED

    decision = ExportDecisionV1(
        ticket_id=ticket_id,
        testcase_version=testcase_version,
        export_format=export_format,
        status=status,
        gate_enabled=gate_enabled,
        gate_mode=mode.value if gate_enabled else "off",
        blockers=actual_blockers,
        warnings=warnings,
        uncovered_requirements=[
            item.object_id or item.blocker_id for item in candidates
            if item.category == "UNCOVERED_ACCEPTANCE_CRITERION"
        ],
        unsupported_results=[
            item.object_id or item.blocker_id for item in candidates
            if item.category == "UNSUPPORTED_EXPECTED_RESULT"
        ],
        conflicts=[
            item.object_id or item.blocker_id for item in candidates
            if item.category == "UNREVIEWED_CONFLICT"
        ],
        approval_status=approval,
        override=override,
        traceability_summary=traceability.summary,
    )
    atomic_write_json(
        _root(ticket_id) / "test-design" / "export_gate_status.json",
        decision.model_dump(mode="json"),
    )
    return decision


def guard_export(
    *,
    ticket_id: str,
    testcases: list[dict],
    testcase_version: str,
    export_format: str,
) -> ExportDecisionV1:
    # Preserve the Phase 9 block-export behavior when the Phase 10 quality
    # gate is not enabled. Once Phase 10 is enabled, its configured rules and
    # override audit are the single export decision point.
    if not export_quality_gate_enabled():
        from app.services.test_quality_review.service import (
            assert_test_quality_export_allowed,
        )

        assert_test_quality_export_allowed(ticket_id)
    decision = evaluate_export(
        ticket_id=ticket_id,
        testcases=testcases,
        testcase_version=testcase_version,
        export_format=export_format,
    )
    if decision.status == ExportGateStatus.BLOCKED:
        blocker_ids = ", ".join(item.blocker_id for item in decision.blockers)
        raise ValueError(
            "Test-case export is blocked by the configured traceability/quality gate. "
            f"Blockers: {blocker_ids}"
        )
    return decision


def create_export_override(
    *,
    ticket_id: str,
    testcases: list[dict],
    testcase_version: str,
    export_format: str,
    reason: str,
    user_identity: str,
    affected_blocker_ids: list[str],
    scope: str,
) -> dict:
    user_identity = str(user_identity or "").strip()
    reason = str(reason or "").strip()
    scope = str(scope or "").strip()
    if not user_identity:
        raise PermissionError("Anonymous export override is not permitted.")
    if user_identity not in authorized_qa_leads():
        raise PermissionError("User is not authorized to override the export gate.")
    if not reason:
        raise ValueError("Override reason is required.")
    valid_scopes = {f"{export_format}:{testcase_version}", "all_testcase_exports"}
    if scope not in valid_scopes:
        raise ValueError(f"Override scope must be one of: {sorted(valid_scopes)}")
    decision = evaluate_export(
        ticket_id=ticket_id,
        testcases=testcases,
        testcase_version=testcase_version,
        export_format=export_format,
        include_overrides=False,
    )
    current_ids = {item.blocker_id for item in decision.blockers}
    affected = {str(item).strip() for item in affected_blocker_ids if str(item).strip()}
    if not current_ids:
        raise ValueError("There are no configured export blockers to override.")
    if not current_ids.issubset(affected):
        missing = sorted(current_ids - affected)
        raise ValueError(f"Override must identify every affected blocker: {missing}")

    override = ExportOverrideV1(
        override_id=f"OVR-{uuid.uuid4().hex[:12]}",
        ticket_id=ticket_id,
        reason=reason,
        user_identity=user_identity,
        timestamp=datetime.now(timezone.utc).isoformat(),
        affected_blocker_ids=sorted(affected),
        scope=scope,
    )
    path = _override_log(ticket_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(override.model_dump(mode="json"), ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())
    return override.model_dump(mode="json")
