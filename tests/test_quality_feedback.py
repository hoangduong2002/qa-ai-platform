from __future__ import annotations

import json

import pytest

from app.services.quality_feedback.models import FeedbackAction, FeedbackReason, VersionMetadata
from app.services.quality_feedback.service import (
    aggregate_feedback,
    canonical_content_hash,
    list_feedback,
    record_testcase_feedback,
)
from evaluation.quality_report import build_continuous_quality_report


def _versions() -> VersionMetadata:
    return VersionMetadata(
        dataset_version="1.0.0",
        generator_version="v2",
        reviewer_version="reviewer-v1",
        prompt_versions={"generator": "sha256:abc"},
        model_identifiers=["provider:model"],
    )


def test_feedback_persistence_hashing_redaction_and_privacy_safe_aggregation(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QA_FEEDBACK_REVIEWER_IDS", "qa.user")
    original = {"title": "Pay invoice", "test_case_id": "TC-1", "secret": "source detail"}
    edited = {"test_case_id": "TC-1", "title": "Pay a valid invoice"}

    event = record_testcase_feedback(
        ticket_id="SECRET-123",
        test_case_id="TC-1",
        testcase_version="v2",
        action=FeedbackAction.ACCEPTED_WITH_EDIT,
        original_content=original,
        edited_content=edited,
        user="qa.user",
        reason_codes=[FeedbackReason.UNCLEAR_STEP],
        comment="Contact owner@example.com with Bearer abc.def.ghi",
        versions=_versions(),
        durations_seconds={"review": 12.0},
        estimated_qa_correction_minutes=3,
    )

    assert event.original_content_hash == canonical_content_hash(original)
    assert event.edited_content_hash == canonical_content_hash(edited)
    stored = list_feedback("SECRET-123")
    assert len(stored) == 1
    assert "owner@example.com" not in stored[0].comment
    assert "abc.def.ghi" not in stored[0].comment

    summary = aggregate_feedback(stored).model_dump(mode="json")
    serialized = json.dumps(summary)
    assert "Pay invoice" not in serialized
    assert "source detail" not in serialized
    assert summary["metrics"]["test_design"]["qa_edit_rate"] == 1.0
    assert summary["metrics"]["efficiency"]["average_review_duration_seconds"] == 12.0
    assert summary["version_breakdown"]["generator"] == {"v2": 1}

    report = build_continuous_quality_report(
        stored,
        {
            "dataset_id": "golden",
            "dataset_version": "1.2.3",
            "versions": {"generator": "v2"},
            "aggregate_metrics": {
                "acceptance_criteria_coverage": 0.9,
                "precision_at_5": 0.8,
                "schema_valid_response_rate": 1.0,
            },
        },
    )
    report_text = json.dumps(report)
    assert report["metrics"]["test_design"]["acceptance_criteria_coverage"] == 0.9
    assert report["metrics"]["retrieval"]["precision_at_5"] == 0.8
    assert "Pay invoice" not in report_text
    assert "defect-leakage causation" in report["methodology_note"]


def test_feedback_authorization_and_edit_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QA_FEEDBACK_REVIEWER_IDS", "qa.user")
    with pytest.raises(PermissionError):
        record_testcase_feedback(
            ticket_id="T-1", test_case_id="TC-1", testcase_version="v1",
            action="REJECTED", original_content={}, user="anonymous", versions=_versions(),
        )
    with pytest.raises(ValueError, match="must differ"):
        record_testcase_feedback(
            ticket_id="T-1", test_case_id="TC-1", testcase_version="v1",
            action="ACCEPTED_WITH_EDIT", original_content={"a": 1}, edited_content={"a": 1},
            user="qa.user", versions=_versions(),
        )
