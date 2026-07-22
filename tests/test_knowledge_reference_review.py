from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.knowledge_reference_review.authority import is_jira_more_authoritative_than
from app.services.knowledge_reference_review.config import default_authority_policy
from app.services.knowledge_reference_review.models import RequestedDecision
from app.services.knowledge_reference_review.service import (
    accepted_reference_context_rows,
    create_review_request,
    review_reference_decision,
)


class _FakeResponse:
    def __init__(self, results):
        self.results = results


def _fake_result(
    *,
    document_id: str,
    collection_id: str,
    content: str,
    citation: str,
    version: int = 1,
    chunk_index: int = 1,
    confidence: float = 0.9,
):
    return SimpleNamespace(
        document_id=document_id,
        collection_id=collection_id,
        content=content,
        source_citation=citation,
        version=version,
        chunk_index=chunk_index,
        confidence=confidence,
    )


def _seed_jira(ticket_id: str) -> None:
    base = Path("requirements") / ticket_id / "source"
    base.mkdir(parents=True, exist_ok=True)
    (base / "description.md").write_text(
        "The fee is 10 and effective date is 2026-07-01. This rule is required.",
        encoding="utf-8",
    )
    (base / "comments.md").write_text("Status is enabled.", encoding="utf-8")


def test_authority_ordering_default_policy_prefers_jira() -> None:
    policy = default_authority_policy()
    assert is_jira_more_authoritative_than("BUSINESS_RULE", policy) is True
    assert is_jira_more_authoritative_than("API_SPEC", policy) is True
    assert is_jira_more_authoritative_than("DEFECT", policy) is True


def test_duplicate_review_requests_detected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T1")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-A",
                collection_id="business-rules",
                content="The fee is 10.",
                citation="DOC-A:v1:chunk1",
            )
        ]
    )

    first = create_review_request(
        ticket_id="T1",
        kb_id="KB1",
        query="fee",
        retrieval_need="Confirm fee",
        jira_issue_being_clarified="What is fee value?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )
    second = create_review_request(
        ticket_id="T1",
        kb_id="KB1",
        query="fee",
        retrieval_need="Confirm fee",
        jira_issue_being_clarified="What is fee value?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True


def test_missing_reviewer_identity_rejected_when_required(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T2")

    provider = lambda _kb, _req: _FakeResponse([])

    with pytest.raises(ValueError):
        create_review_request(
            ticket_id="T2",
            kb_id="KB1",
            query="fee",
            retrieval_need="Confirm fee",
            jira_issue_being_clarified="What is fee value?",
            reviewer_id="",
            search_provider=provider,
        )


def test_authorization_required_for_decisions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.allowed")
    _seed_jira("T3")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-A",
                collection_id="business-rules",
                content="The fee is 10 and required.",
                citation="DOC-A:v1:chunk1",
            )
        ]
    )

    payload = create_review_request(
        ticket_id="T3",
        kb_id="KB1",
        query="fee",
        retrieval_need="Confirm fee",
        jira_issue_being_clarified="What is fee value?",
        reviewer_id="qa.allowed",
        search_provider=provider,
    )

    source_result_id = payload["candidates"][0]["result_id"]

    with pytest.raises(PermissionError):
        review_reference_decision(
            ticket_id="T3",
            source_result_id=source_result_id,
            requested_decision=RequestedDecision.ACCEPT,
            decision_reason="Looks good",
            review_note="",
            reviewed_by="qa.denied",
        )


def test_conflicting_numeric_and_date_values_are_detected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T4")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-NUM",
                collection_id="api-spec",
                content="The fee is 12 and effective date is 2026-08-01.",
                citation="DOC-NUM:v1:chunk1",
            )
        ]
    )

    payload = create_review_request(
        ticket_id="T4",
        kb_id="KB1",
        query="fee and date",
        retrieval_need="Confirm fee and date",
        jira_issue_being_clarified="Which fee/date are valid?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )

    decision = review_reference_decision(
        ticket_id="T4",
        source_result_id=payload["candidates"][0]["result_id"],
        requested_decision=RequestedDecision.ACCEPT,
        decision_reason="Attempt accept",
        review_note="",
        reviewed_by="qa.reviewer",
    )

    conflict_types = {item["conflict_type"] for item in decision["conflicts"]}
    assert "VALUE_MISMATCH" in conflict_types
    assert "DATE_MISMATCH" in conflict_types
    assert decision["reviewed"]["classification"] in {"NEEDS_CONFIRMATION", "CONFLICT"}


def test_outdated_reference_detection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T5")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-OLD",
                collection_id="historical-defect",
                content="Legacy behavior from old release.",
                citation="DOC-OLD:v1:chunk1",
            )
        ]
    )

    payload = create_review_request(
        ticket_id="T5",
        kb_id="KB1",
        query="legacy behavior",
        retrieval_need="Historical context",
        jira_issue_being_clarified="Does historical behavior still apply?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )

    # Force outdated metadata in candidate artifact for deterministic check.
    candidate_file = Path("requirements") / "T5" / "knowledge" / "candidate_references.json"
    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    candidates[0]["effective_to"] = "2020-01-01T00:00:00Z"
    candidates[0]["status"] = "ARCHIVED"
    candidate_file.write_text(json.dumps(candidates, indent=2), encoding="utf-8")

    decision = review_reference_decision(
        ticket_id="T5",
        source_result_id=payload["candidates"][0]["result_id"],
        requested_decision=RequestedDecision.MARK_OUTDATED,
        decision_reason="Expired reference",
        review_note="Out of date",
        reviewed_by="qa.reviewer",
    )

    conflict_types = {item["conflict_type"] for item in decision["conflicts"]}
    assert "OUTDATED_REFERENCE" in conflict_types
    assert decision["reviewed"]["classification"] == "OUTDATED"


def test_accepted_only_context_and_rejected_exclusion(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T6")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-OK",
                collection_id="business-rules",
                content="The fee is 10 and required.",
                citation="DOC-OK:v1:chunk1",
            ),
            _fake_result(
                document_id="DOC-BAD",
                collection_id="observed-behavior",
                content="The fee is optional and currently behaves differently.",
                citation="DOC-BAD:v1:chunk1",
                chunk_index=2,
            ),
        ]
    )

    payload = create_review_request(
        ticket_id="T6",
        kb_id="KB1",
        query="fee",
        retrieval_need="Confirm fee",
        jira_issue_being_clarified="What is fee rule?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )

    ids = [item["result_id"] for item in payload["candidates"]]

    review_reference_decision(
        ticket_id="T6",
        source_result_id=ids[0],
        requested_decision=RequestedDecision.ACCEPT,
        decision_reason="Matches Jira",
        review_note="",
        reviewed_by="qa.reviewer",
    )

    review_reference_decision(
        ticket_id="T6",
        source_result_id=ids[1],
        requested_decision=RequestedDecision.REJECT,
        decision_reason="Contradicts Jira",
        review_note="",
        reviewed_by="qa.reviewer",
    )

    selected_file = Path("requirements") / "T6" / "knowledge" / "selected_references.json"
    rejected_file = Path("requirements") / "T6" / "knowledge" / "rejected_references.json"

    selected = json.loads(selected_file.read_text(encoding="utf-8"))
    rejected = json.loads(rejected_file.read_text(encoding="utf-8"))

    assert len(selected) == 1
    assert selected[0]["source_result_id"] == ids[0]
    assert any(item["source_result_id"] == ids[1] for item in rejected)

    accepted_rows = accepted_reference_context_rows("T6")
    assert all(item["classification"] == "ACCEPTED" for item in accepted_rows)


def test_audit_trail_written(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "true")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "qa.reviewer")
    _seed_jira("T7")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-AUDIT",
                collection_id="business-rules",
                content="The fee is 10 and required.",
                citation="DOC-AUDIT:v1:chunk1",
            )
        ]
    )

    payload = create_review_request(
        ticket_id="T7",
        kb_id="KB1",
        query="fee",
        retrieval_need="Confirm fee",
        jira_issue_being_clarified="What is fee rule?",
        reviewer_id="qa.reviewer",
        search_provider=provider,
    )

    review_reference_decision(
        ticket_id="T7",
        source_result_id=payload["candidates"][0]["result_id"],
        requested_decision=RequestedDecision.ACCEPT,
        decision_reason="Matches Jira",
        review_note="audit",
        reviewed_by="qa.reviewer",
    )

    audit_file = Path("requirements") / "T7" / "knowledge" / "review_audit.jsonl"
    assert audit_file.exists()
    lines = [line for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2


def test_feature_disabled_behavior_allows_anonymous_review(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", "false")
    monkeypatch.setenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "")
    _seed_jira("T8")

    provider = lambda _kb, _req: _FakeResponse(
        [
            _fake_result(
                document_id="DOC-FLAG",
                collection_id="observed-behavior",
                content="The fee may vary currently.",
                citation="DOC-FLAG:v1:chunk1",
            )
        ]
    )

    payload = create_review_request(
        ticket_id="T8",
        kb_id="KB1",
        query="fee",
        retrieval_need="Observe",
        jira_issue_being_clarified="What do we do in practice?",
        reviewer_id="anonymous",
        search_provider=provider,
    )

    result = review_reference_decision(
        ticket_id="T8",
        source_result_id=payload["candidates"][0]["result_id"],
        requested_decision=RequestedDecision.ACCEPT,
        decision_reason="Flag disabled",
        review_note="",
        reviewed_by="",
    )

    assert result["review_required"] is False
    assert result["reviewed"]["reviewed_by"] == "anonymous"
