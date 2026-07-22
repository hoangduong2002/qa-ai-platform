from __future__ import annotations

import hashlib
from typing import Callable

from knowledge.domain.models import SearchRequest
from knowledge.services.runtime import get_knowledge_service

from app.services.knowledge_reference_review.artifacts import (
    append_review_audit,
    read_candidate_references,
    read_review_records,
    read_review_requests,
    save_candidate_references,
    save_conflicts,
    save_reference_context_markdown,
    save_rejected_references,
    save_review_records,
    save_review_requests,
    save_selected_references,
    utc_now_iso,
)
from app.services.knowledge_reference_review.authority import is_jira_more_authoritative_than
from app.services.knowledge_reference_review.config import (
    authorized_reviewers,
    default_authority_policy,
    reference_review_required,
)
from app.services.knowledge_reference_review.conflict_detector import detect_conflicts
from app.services.knowledge_reference_review.jira_source import load_jira_statements
from app.services.knowledge_reference_review.llm_assist import detect_possible_conflicts_with_llm
from app.services.knowledge_reference_review.models import (
    CandidateReference,
    ReferenceClassification,
    RequestedDecision,
    ReviewedReference,
    ReviewRequest,
)
from app.services.knowledge_reference_review.retrieval_config import (
    knowledge_retrieval_enabled,
    knowledge_retrieval_shadow_mode,
)


def _request_id(ticket_id: str, kb_id: str, query: str, retrieval_need: str, jira_issue: str) -> str:
    digest = hashlib.sha1(f"{ticket_id}|{kb_id}|{query}|{retrieval_need}|{jira_issue}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"RR-{digest}"


def _result_id(document_id: str, version: int, chunk_index: int) -> str:
    return f"{document_id}:v{version}:chunk{chunk_index}"


def _to_candidate(*, retrieval_need: str, jira_issue: str, kb_id: str, result) -> CandidateReference:
    return CandidateReference(
        result_id=_result_id(result.document_id, int(result.version), int(result.chunk_index)),
        retrieval_need=retrieval_need,
        jira_issue_being_clarified=jira_issue,
        kb_id=kb_id,
        collection_id=result.collection_id,
        document_id=result.document_id,
        version=int(result.version),
        chunk_index=int(result.chunk_index),
        excerpt=result.content,
        citation=result.source_citation,
        confidence=float(result.confidence),
        source_type=_infer_source_type(result.collection_id, result.document_id),
        status="INDEXED",
        intended_use="analysis",
    )


def _infer_source_type(collection_id: str, document_id: str) -> str:
    key = f"{collection_id}|{document_id}".lower()
    if "api" in key or "integration" in key:
        return "API_SPEC"
    if "rule" in key:
        return "BUSINESS_RULE"
    if "test" in key:
        return "TEST_CASE"
    if "defect" in key or "bug" in key:
        return "DEFECT"
    if "observed" in key or "behavior" in key:
        return "OBSERVED_BEHAVIOR"
    return "UNKNOWN"


def _classification_for_decision(decision: RequestedDecision) -> ReferenceClassification:
    if decision == RequestedDecision.ACCEPT:
        return ReferenceClassification.ACCEPTED
    if decision == RequestedDecision.REJECT:
        return ReferenceClassification.REJECTED
    if decision == RequestedDecision.MARK_OUTDATED:
        return ReferenceClassification.OUTDATED
    if decision == RequestedDecision.MARK_HISTORICAL:
        return ReferenceClassification.HISTORICAL_CONTEXT_ONLY
    return ReferenceClassification.NEEDS_CONFIRMATION


def _material_conflict_exists(conflicts: list[dict]) -> bool:
    for item in conflicts:
        conflict_type = str(item.get("conflict_type", ""))
        if conflict_type in {"CONTRADICTS_JIRA", "DATE_MISMATCH", "VALUE_MISMATCH", "STATUS_MISMATCH", "UNSUPPORTED_BEHAVIOR"}:
            return True
    return False


def _rebuild_artifacts(ticket_id: str) -> dict:
    records = [ReviewedReference.model_validate(item) for item in read_review_records(ticket_id)]

    accepted = [item for item in records if item.classification == ReferenceClassification.ACCEPTED]
    rejected = [item for item in records if item.classification != ReferenceClassification.ACCEPTED]

    all_conflicts = []
    seen = set()
    for record in records:
        for conflict in record.conflicts:
            key = conflict.conflict_id
            if key in seen:
                continue
            seen.add(key)
            all_conflicts.append(conflict.model_dump(mode="json"))

    save_selected_references(ticket_id, accepted)
    save_rejected_references(ticket_id, rejected)
    save_conflicts(ticket_id, all_conflicts)
    save_reference_context_markdown(ticket_id, accepted)

    return {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "conflicts": len(all_conflicts),
    }


def _assert_reviewer_identity(reviewer_id: str) -> None:
    reviewer = (reviewer_id or "").strip()
    if not reviewer:
        raise ValueError("Missing reviewer identity.")


def _assert_reviewer_authorized(reviewer_id: str) -> None:
    allowed = authorized_reviewers()
    if not allowed:
        return

    if reviewer_id.strip() not in set(allowed):
        raise PermissionError("Reviewer is not authorized for knowledge reference decisions.")


def create_review_request(
    *,
    ticket_id: str,
    kb_id: str,
    query: str,
    retrieval_need: str,
    jira_issue_being_clarified: str,
    reviewer_id: str,
    top_k: int = 10,
    search_provider: Callable[[str, SearchRequest], object] | None = None,
) -> dict:
    if not knowledge_retrieval_enabled():
        raise RuntimeError(
            "Knowledge retrieval is disabled by KNOWLEDGE_RETRIEVAL_ENABLED."
        )
    _assert_reviewer_identity(reviewer_id)
    if reference_review_required():
        _assert_reviewer_authorized(reviewer_id)

    request_id = _request_id(ticket_id, kb_id, query, retrieval_need, jira_issue_being_clarified)

    requests = read_review_requests(ticket_id)
    for item in requests:
        if not isinstance(item, dict):
            continue
        if item.get("request_id") == request_id and item.get("status") == "OPEN":
            return {
                "duplicate": True,
                "request": item,
                "candidates": [entry for entry in read_candidate_references(ticket_id) if entry.get("request_id") == request_id],
            }

    provider = search_provider or (lambda local_kb_id, request: get_knowledge_service().search(local_kb_id, request))
    response = provider(kb_id, SearchRequest(query=query, top_k=top_k))

    candidates = []
    for result in response.results:
        candidate = _to_candidate(
            retrieval_need=retrieval_need,
            jira_issue=jira_issue_being_clarified,
            kb_id=kb_id,
            result=result,
        ).model_dump(mode="json")
        candidate["request_id"] = request_id
        candidates.append(candidate)

    existing_candidates = read_candidate_references(ticket_id)
    existing_candidates.extend(candidates)
    save_candidate_references(ticket_id, existing_candidates)

    request = ReviewRequest(
        request_id=request_id,
        ticket_id=ticket_id,
        retrieval_need=retrieval_need,
        jira_issue_being_clarified=jira_issue_being_clarified,
        query=query,
        kb_id=kb_id,
        created_at=utc_now_iso(),
        created_by=reviewer_id,
        result_ids=[item["result_id"] for item in candidates],
    )

    requests.append(request.model_dump(mode="json"))
    save_review_requests(ticket_id, requests)

    append_review_audit(
        ticket_id,
        {
            "event": "review_request_created",
            "request_id": request_id,
            "ticket_id": ticket_id,
            "query": query,
            "kb_id": kb_id,
            "created_by": reviewer_id,
            "created_at": utc_now_iso(),
            "candidate_count": len(candidates),
            "retrieval_shadow_mode": knowledge_retrieval_shadow_mode(),
        },
    )

    return {
        "duplicate": False,
        "retrieval_shadow_mode": knowledge_retrieval_shadow_mode(),
        "request": request.model_dump(mode="json"),
        "candidates": candidates,
    }


def review_reference_decision(
    *,
    ticket_id: str,
    source_result_id: str,
    requested_decision: RequestedDecision,
    decision_reason: str,
    review_note: str,
    reviewed_by: str,
    ai_mode: str | None = None,
) -> dict:
    required = reference_review_required()

    if required:
        _assert_reviewer_identity(reviewed_by)
        _assert_reviewer_authorized(reviewed_by)
    elif not (reviewed_by or "").strip():
        reviewed_by = "anonymous"

    candidates = read_candidate_references(ticket_id)
    candidate_row = None
    for item in candidates:
        if isinstance(item, dict) and item.get("result_id") == source_result_id:
            candidate_row = item
            break

    if candidate_row is None:
        raise ValueError(f"Candidate reference not found: {source_result_id}")

    candidate = CandidateReference.model_validate(candidate_row)
    jira_statements = load_jira_statements(ticket_id)

    records = read_review_records(ticket_id)
    accepted_refs = [item for item in records if isinstance(item, dict) and item.get("classification") == "ACCEPTED"]

    deterministic_conflicts = detect_conflicts(
        candidate=candidate,
        jira_statements=jira_statements,
        authority_policy=default_authority_policy(),
        accepted_references=accepted_refs,
    )

    llm_conflicts = detect_possible_conflicts_with_llm(
        ai_mode=ai_mode,
        jira_statements=[item.model_dump(mode="json") for item in jira_statements],
        candidate=candidate.model_dump(mode="json"),
    )

    conflicts = [item.model_dump(mode="json") for item in deterministic_conflicts]
    for index, item in enumerate(llm_conflicts, start=1):
        if not isinstance(item, dict):
            continue
        conflicts.append(
            {
                "conflict_id": f"CF-LLM-{source_result_id}-{index}",
                "source_result_id": source_result_id,
                "jira_statement": jira_statements[0].text if jira_statements else "",
                "jira_source": jira_statements[0].source if jira_statements else "jira",
                "kb_statement": candidate.excerpt,
                "kb_source": candidate.citation,
                "conflict_type": "UNSUPPORTED_BEHAVIOR",
                "severity": "MEDIUM",
                "authoritative_source": "CURRENT_JIRA_TICKET",
                "recommended_action": f"LLM-assist note: {item.get('rationale', 'Needs review')}",
                "human_confirmation_required": True,
            }
        )

    classification = _classification_for_decision(requested_decision)

    if required and requested_decision == RequestedDecision.ACCEPT and _material_conflict_exists(conflicts):
        classification = ReferenceClassification.NEEDS_CONFIRMATION

    if required and requested_decision == RequestedDecision.ACCEPT:
        if not is_jira_more_authoritative_than(candidate.source_type, default_authority_policy()):
            classification = ReferenceClassification.CONFLICT

    reviewed = ReviewedReference(
        ticket_id=ticket_id,
        source_result_id=candidate.result_id,
        classification=classification,
        requested_decision=requested_decision,
        reviewed_by=reviewed_by,
        reviewed_at=utc_now_iso(),
        review_note=review_note,
        decision_reason=decision_reason,
        retrieval_need=candidate.retrieval_need,
        jira_issue_being_clarified=candidate.jira_issue_being_clarified,
        kb_id=candidate.kb_id,
        collection_id=candidate.collection_id,
        document_id=candidate.document_id,
        version=candidate.version,
        chunk_index=candidate.chunk_index,
        excerpt=candidate.excerpt,
        citation=candidate.citation,
        confidence=candidate.confidence,
        effective_from=candidate.effective_from,
        effective_to=candidate.effective_to,
        source_type=candidate.source_type,
        status=candidate.status,
        intended_use=candidate.intended_use,
        conflicts=deterministic_conflicts,
    )

    updated_records = [
        item for item in records
        if not (isinstance(item, dict) and item.get("source_result_id") == source_result_id)
    ]
    updated_records.append(reviewed.model_dump(mode="json"))
    save_review_records(ticket_id, updated_records)

    summary = _rebuild_artifacts(ticket_id)

    append_review_audit(
        ticket_id,
        {
            "event": "reference_reviewed",
            "ticket_id": ticket_id,
            "source_result_id": source_result_id,
            "requested_decision": requested_decision.value,
            "classification": classification.value,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed.reviewed_at,
            "review_note": review_note,
            "decision_reason": decision_reason,
            "conflict_count": len(conflicts),
        },
    )

    return {
        "reviewed": reviewed.model_dump(mode="json"),
        "conflicts": conflicts,
        "summary": summary,
        "review_required": required,
    }


def load_review_dashboard(ticket_id: str) -> dict:
    candidates = [item for item in read_candidate_references(ticket_id) if isinstance(item, dict)]
    requests = [item for item in read_review_requests(ticket_id) if isinstance(item, dict)]
    records = [item for item in read_review_records(ticket_id) if isinstance(item, dict)]

    reviewed_map = {item.get("source_result_id"): item for item in records}

    rows = []
    for candidate in candidates:
        rows.append(
            {
                **candidate,
                "review": reviewed_map.get(candidate.get("result_id"), {}),
            }
        )

    return {
        "ticket_id": ticket_id,
        "review_required": reference_review_required(),
        "requests": requests,
        "candidates": rows,
        "review_count": len(records),
    }


def accepted_reference_context_rows(ticket_id: str) -> list[dict]:
    records = [item for item in read_review_records(ticket_id) if isinstance(item, dict)]

    if reference_review_required():
        return [item for item in records if item.get("classification") == ReferenceClassification.ACCEPTED.value]

    return [
        item for item in records
        if item.get("classification") in {
            ReferenceClassification.ACCEPTED.value,
            ReferenceClassification.HISTORICAL_CONTEXT_ONLY.value,
        }
    ]
