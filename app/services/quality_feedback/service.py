from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.quality_feedback.models import (
    FeedbackAction,
    FeedbackEvent,
    FeedbackReason,
    FeedbackSummary,
    VersionMetadata,
)
from app.services.quality_feedback.privacy import redact_text
from app.services.quality_feedback.versions import version_metadata


def authorized_feedback_reviewers() -> set[str]:
    raw = os.getenv("QA_FEEDBACK_REVIEWER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def canonical_content_hash(content: Any) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _feedback_file(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "feedback" / "testcase_feedback.jsonl"


def _authorize(user: str) -> str:
    clean = " ".join((user or "").split())
    if not clean:
        raise PermissionError("Feedback requires an authenticated reviewer identity.")
    if clean not in authorized_feedback_reviewers():
        raise PermissionError(f"User {clean!r} is not authorized to submit QA feedback.")
    return clean


def record_testcase_feedback(
    *,
    ticket_id: str,
    test_case_id: str,
    testcase_version: str,
    action: FeedbackAction | str,
    original_content: Any,
    user: str,
    reason_codes: list[FeedbackReason | str] | None = None,
    edited_content: Any | None = None,
    comment: str | None = None,
    versions: VersionMetadata | None = None,
    domain: str = "unspecified",
    durations_seconds: dict[str, float] | None = None,
    estimated_qa_correction_minutes: float | None = None,
) -> FeedbackEvent:
    reviewer = _authorize(user)
    parsed_action = FeedbackAction(action)
    parsed_reasons = [FeedbackReason(item) for item in (reason_codes or [])]
    event = FeedbackEvent(
        event_id=f"QAF-{uuid.uuid4().hex}",
        ticket_id=ticket_id,
        test_case_id=test_case_id,
        testcase_version=testcase_version or "latest",
        action=parsed_action,
        reason_codes=parsed_reasons,
        user=reviewer,
        timestamp=datetime.now().astimezone().isoformat(),
        original_content_hash=canonical_content_hash(original_content),
        edited_content_hash=(
            canonical_content_hash(edited_content) if edited_content is not None else None
        ),
        comment=redact_text(comment, max_length=1000) if comment else None,
        versions=versions or version_metadata(ticket_id),
        domain=" ".join((domain or "unspecified").split()) or "unspecified",
        durations_seconds=durations_seconds or {},
        estimated_qa_correction_minutes=estimated_qa_correction_minutes,
    )
    path = _feedback_file(ticket_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return event


def list_feedback(ticket_id: str) -> list[FeedbackEvent]:
    path = _feedback_file(ticket_id)
    if not path.exists():
        return []
    events: list[FeedbackEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(FeedbackEvent.model_validate_json(line))
    return events


def aggregate_feedback(events: list[FeedbackEvent]) -> FeedbackSummary:
    actions = Counter(item.action.value for item in events)
    reasons = Counter(reason.value for item in events for reason in item.reason_codes)
    domains = Counter(item.domain for item in events)
    versions: dict[str, Counter[str]] = {
        "generator": Counter(item.versions.generator_version for item in events),
        "reviewer": Counter(item.versions.reviewer_version for item in events),
        "retrieval": Counter(item.versions.retrieval_version for item in events),
        "ranking": Counter(item.versions.ranking_version for item in events),
    }
    total = len(events)
    accepted = actions[FeedbackAction.ACCEPTED_WITHOUT_EDIT.value] + actions[FeedbackAction.ACCEPTED_WITH_EDIT.value]
    edited = actions[FeedbackAction.ACCEPTED_WITH_EDIT.value]
    rejected = actions[FeedbackAction.REJECTED.value]
    duration_keys = ("analysis", "generation", "review")
    efficiency = {
        f"average_{key}_duration_seconds": (
            sum(item.durations_seconds.get(key, 0.0) for item in events if key in item.durations_seconds)
            / max(1, sum(1 for item in events if key in item.durations_seconds))
        )
        for key in duration_keys
    }
    correction_values = [
        item.estimated_qa_correction_minutes
        for item in events
        if item.estimated_qa_correction_minutes is not None
    ]
    efficiency["estimated_qa_correction_minutes"] = (
        sum(correction_values) / len(correction_values) if correction_values else None
    )
    return FeedbackSummary(
        generated_at=datetime.now().astimezone().isoformat(),
        event_count=total,
        action_counts=dict(actions),
        reason_counts=dict(reasons),
        metrics={
            "requirement_analysis": {
                "structured_analysis_acceptance": accepted / total if total else 0.0,
                "missing_information_recall": None,
                "ambiguity_precision": None,
                "unsupported_assumption_rate": reasons[FeedbackReason.UNSUPPORTED_ASSUMPTION.value] / total if total else 0.0,
                "contradiction_detection_rate": None,
            },
            "retrieval": {
                "precision_at_5": None,
                "recall_at_10": None,
                "accepted_reference_rate": 1.0 - (reasons[FeedbackReason.INCORRECT_REFERENCE.value] / total) if total else 0.0,
                "outdated_reference_rate": reasons[FeedbackReason.OUTDATED_KNOWLEDGE.value] / total if total else 0.0,
                "exact_code_accuracy": None,
            },
            "test_design": {
                "acceptance_criteria_coverage": None,
                "critical_condition_coverage": None,
                "duplicate_rate": actions[FeedbackAction.DUPLICATE.value] / total if total else 0.0,
                "unsupported_result_rate": actions[FeedbackAction.INCORRECT_EXPECTED_RESULT.value] / total if total else 0.0,
                "qa_edit_rate": edited / total if total else 0.0,
                "qa_rejection_rate": rejected / total if total else 0.0,
                "average_issues_per_test_case": sum(reasons.values()) / total if total else 0.0,
                "export_approval_rate": accepted / total if total else 0.0,
            },
            "efficiency": efficiency,
        },
        version_breakdown={key: dict(value) for key, value in versions.items()},
        model_identifiers=sorted({model for item in events for model in item.versions.model_identifiers}),
        model_configurations=[
            json.loads(value)
            for value in sorted({
                json.dumps(item.versions.model_configuration, sort_keys=True)
                for item in events
                if item.versions.model_configuration
            })
        ],
        domain_breakdown=dict(domains),
    )


def ticket_feedback_summary(ticket_id: str) -> dict[str, Any]:
    return aggregate_feedback(list_feedback(ticket_id)).model_dump(mode="json")


def ticket_quality_dashboard(ticket_id: str) -> dict[str, Any]:
    summary = ticket_feedback_summary(ticket_id)
    report_path = Path("requirements") / ticket_id / "test-design" / "test_quality_report.json"
    try:
        quality_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        quality_report = {}
    events = list_feedback(ticket_id)
    return {
        "summary": summary,
        "recent_feedback": [item.model_dump(mode="json") for item in events[-10:]],
        "missing_coverage": quality_report.get("missing_coverage", []),
        "quality_review_status": quality_report.get("review_status"),
    }
