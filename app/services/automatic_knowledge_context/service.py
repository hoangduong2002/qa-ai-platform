from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from app.services.automatic_knowledge_context.artifacts import (
    create_snapshot_id,
    load_latest_snapshot,
    save_snapshot,
    update_ticket_knowledge_metadata,
    utc_now_iso,
)
from app.services.automatic_knowledge_context.config import (
    max_context_characters,
    max_retrieved_references,
    max_selected_references,
    minimum_score,
    top_k_per_query,
)
from app.services.automatic_knowledge_context.models import (
    KnowledgeRetrievalSnapshot,
    KnowledgeRetrievalStatus,
    KnowledgeSnapshotReference,
)
from app.services.automatic_knowledge_context.prompt_builder import (
    build_knowledge_prompt_context,
)
from app.services.automatic_knowledge_context.query_builder import (
    build_retrieval_queries,
    classify_collection_roles,
)
from app.services.jira_project_key_service import extract_jira_project_key
from app.services.knowledge_reference_review.artifacts import (
    read_candidate_references,
    read_review_records,
    read_review_requests,
    save_candidate_references,
    save_review_requests,
)
from app.services.knowledge_reference_review.retrieval_config import (
    knowledge_retrieval_enabled,
    knowledge_retrieval_shadow_mode,
)
from knowledge.domain.models import SearchRequest
from knowledge.services.config import knowledge_base_enabled
from knowledge.services.runtime import get_knowledge_service
from knowledge.storage.utils import validate_identifier


logger = logging.getLogger(__name__)


def _requirement_dir(ticket_id: str) -> Path:
    return Path("requirements") / validate_identifier(ticket_id, "ticket_id")


def _read_ticket(ticket_id: str) -> dict:
    path = _requirement_dir(ticket_id) / "ticket.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _authority(category: str, collection_id: str) -> str:
    text = f"{category} {collection_id}".lower()
    if "business" in text or "domain" in text or "spec" in text:
        return "authoritative"
    if "defect" in text or "histor" in text or "bug" in text:
        return "historical"
    if "guideline" in text or "profile" in text:
        return "guideline"
    return "supporting"


def _source_result_id(kb_id: str, collection_id: str, document_id: str, version: int, chunk_index: int) -> str:
    value = f"{kb_id}|{collection_id}|{document_id}|{version}|{chunk_index}"
    return f"KBREF-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16].upper()}"


def _status_snapshot(
    *,
    ticket_id: str,
    analysis_run_id: str,
    status: KnowledgeRetrievalStatus,
    message: str,
    jira_issue_key: str | None,
    jira_project_key: str | None,
    knowledge_base_id: str | None = None,
    knowledge_base_name: str | None = None,
    started: float,
    failure_reason: str | None = None,
) -> KnowledgeRetrievalSnapshot:
    return KnowledgeRetrievalSnapshot(
        snapshot_id=create_snapshot_id(),
        ticket_id=ticket_id,
        analysis_run_id=analysis_run_id,
        jira_issue_key=jira_issue_key,
        jira_project_key=jira_project_key,
        knowledge_base_id=knowledge_base_id,
        knowledge_base_name=knowledge_base_name,
        status=status,
        status_message=message,
        created_at=utc_now_iso(),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        failure_reason=failure_reason,
    )


def _persist(snapshot: KnowledgeRetrievalSnapshot) -> KnowledgeRetrievalSnapshot:
    save_snapshot(snapshot)
    update_ticket_knowledge_metadata(snapshot)
    logger.info(
        "knowledge_retrieval status=%s ticket_id=%s jira_project_key=%s kb_id=%s "
        "queries=%s retrieved=%s selected=%s snapshot_id=%s elapsed_ms=%s",
        snapshot.status.value,
        snapshot.ticket_id,
        snapshot.jira_project_key or "",
        snapshot.knowledge_base_id or "",
        len(snapshot.queries),
        snapshot.retrieved_count,
        snapshot.selected_count,
        snapshot.snapshot_id,
        snapshot.elapsed_ms,
    )
    return snapshot


def _sync_review_artifacts(snapshot: KnowledgeRetrievalSnapshot) -> None:
    candidates = [
        item
        for item in read_candidate_references(snapshot.ticket_id)
        if isinstance(item, dict)
    ]
    new_rows = []
    for item in snapshot.references:
        new_rows.append(
            {
                "result_id": item.source_result_id,
                "retrieval_need": ", ".join(item.matched_query_categories),
                "jira_issue_being_clarified": snapshot.jira_issue_key or snapshot.ticket_id,
                "kb_id": item.kb_id,
                "collection_id": item.collection_id,
                "document_id": item.document_id,
                "version": item.document_version,
                "chunk_index": item.chunk_index,
                "excerpt": item.excerpt,
                "citation": item.citation,
                "confidence": item.confidence,
                "source_type": item.source_type,
                "status": "INDEXED",
                "intended_use": "analysis",
                "snapshot_id": snapshot.snapshot_id,
                "reference_id": item.reference_id,
                "score": item.score,
                "authority": item.authority,
                "selected": item.selected,
                "used_in_prompt": item.used_in_prompt,
            }
        )
    new_ids = {item["result_id"] for item in new_rows}
    candidates = [item for item in candidates if item.get("result_id") not in new_ids]
    candidates.extend(new_rows)
    save_candidate_references(snapshot.ticket_id, candidates)

    requests = [
        item for item in read_review_requests(snapshot.ticket_id) if isinstance(item, dict)
    ]
    request_id = f"AUTO-{snapshot.snapshot_id}"
    requests.append(
        {
            "request_id": request_id,
            "ticket_id": snapshot.ticket_id,
            "retrieval_need": "Automatic Requirement Analysis context",
            "jira_issue_being_clarified": snapshot.jira_issue_key or snapshot.ticket_id,
            "query": " | ".join(item.query for item in snapshot.queries),
            "kb_id": snapshot.knowledge_base_id,
            "created_at": snapshot.created_at,
            "created_by": "automatic-retrieval",
            "status": "OPEN",
            "result_ids": [item.source_result_id for item in snapshot.references],
            "snapshot_id": snapshot.snapshot_id,
        }
    )
    save_review_requests(snapshot.ticket_id, requests)


def _reviewed_snapshot(
    *,
    ticket_id: str,
    analysis_run_id: str,
    adjusted_by: str,
) -> KnowledgeRetrievalSnapshot | None:
    base = load_latest_snapshot(ticket_id)
    if base is None or not base.references:
        return None
    decisions = {
        item.get("source_result_id"): item.get("classification")
        for item in read_review_records(ticket_id)
        if isinstance(item, dict)
    }
    selected_count = 0
    selected_chars = 0
    references = []
    for item in base.references:
        clone = item.model_copy(deep=True)
        decision = decisions.get(clone.source_result_id)
        desired = clone.selected
        if decision == "ACCEPTED":
            desired = True
        elif decision in {"REJECTED", "OUTDATED", "CONFLICT", "NEEDS_CONFIRMATION"}:
            desired = False
        allowed = (
            desired
            and selected_count < max_selected_references()
            and selected_chars + len(clone.excerpt) <= max_context_characters()
        )
        clone.selected = allowed
        clone.used_in_prompt = allowed
        if allowed:
            selected_count += 1
            selected_chars += len(clone.excerpt)
        references.append(clone)
    snapshot = base.model_copy(
        update={
            "snapshot_id": create_snapshot_id(),
            "analysis_run_id": analysis_run_id,
            "created_at": utc_now_iso(),
            "status": (
                KnowledgeRetrievalStatus.COMPLETED
                if selected_count
                else KnowledgeRetrievalStatus.NO_MATCHES
            ),
            "status_message": (
                "Reviewed Knowledge reference selection prepared for Analysis."
                if selected_count
                else "The reviewed selection contains no references for Analysis."
            ),
            "selected_count": selected_count,
            "references": references,
            "selection_mode": "reviewed",
            "based_on_snapshot_id": base.snapshot_id,
            "adjusted_by": adjusted_by or "reviewer",
            "adjusted_at": utc_now_iso(),
            "elapsed_ms": 0,
        },
        deep=True,
    )
    return _persist(snapshot)


def prepare_knowledge_context(
    *,
    ticket_id: str,
    analysis_run_id: str,
    requirement_context: str,
    use_reviewed_references: bool = False,
    adjusted_by: str = "",
    knowledge_service=None,
) -> tuple[KnowledgeRetrievalSnapshot, str]:
    """Resolve, retrieve, persist, and render Knowledge for one Analysis run."""
    started = time.monotonic()
    ticket = _read_ticket(ticket_id)
    issue_key = str(ticket.get("jira_key") or ticket.get("ticket_id") or ticket_id)
    project_key = ticket.get("jira_project_key")
    if not project_key and str(ticket.get("source_type") or "") == "jira":
        project_key = extract_jira_project_key(None, issue_key)

    if use_reviewed_references:
        reviewed = _reviewed_snapshot(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            adjusted_by=adjusted_by,
        )
        if reviewed is not None:
            return reviewed, build_knowledge_prompt_context(reviewed)

    if not knowledge_base_enabled():
        snapshot = _status_snapshot(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            status=KnowledgeRetrievalStatus.DISABLED,
            message="Knowledge Base is disabled. Analysis ran without Knowledge context.",
            jira_issue_key=issue_key,
            jira_project_key=project_key,
            started=started,
        )
        return _persist(snapshot), build_knowledge_prompt_context(snapshot)
    if not knowledge_retrieval_enabled():
        snapshot = _status_snapshot(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            status=KnowledgeRetrievalStatus.RETRIEVAL_DISABLED,
            message="Knowledge retrieval is disabled. Analysis ran without Knowledge context.",
            jira_issue_key=issue_key,
            jira_project_key=project_key,
            started=started,
        )
        return _persist(snapshot), build_knowledge_prompt_context(snapshot)
    if not project_key:
        snapshot = _status_snapshot(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            status=KnowledgeRetrievalStatus.NO_PROJECT_KEY,
            message="No Jira Project Key is available. Analysis ran without Knowledge context.",
            jira_issue_key=issue_key,
            jira_project_key=None,
            started=started,
        )
        return _persist(snapshot), build_knowledge_prompt_context(snapshot)

    service = knowledge_service or get_knowledge_service()
    try:
        kb = service.resolve_kb_by_jira_project_key(project_key)
        if kb is None:
            snapshot = _status_snapshot(
                ticket_id=ticket_id,
                analysis_run_id=analysis_run_id,
                status=KnowledgeRetrievalStatus.NO_MAPPING,
                message=f'No Knowledge Base is mapped to Jira project "{project_key}".',
                jira_issue_key=issue_key,
                jira_project_key=project_key,
                started=started,
            )
            return _persist(snapshot), build_knowledge_prompt_context(snapshot)
        if not kb.enabled or not service.kb_health(kb.kb_id).get("index_exists"):
            snapshot = _status_snapshot(
                ticket_id=ticket_id,
                analysis_run_id=analysis_run_id,
                status=KnowledgeRetrievalStatus.KB_NOT_READY,
                message=f'Knowledge Base "{kb.kb_id}" has no searchable published index.',
                jira_issue_key=issue_key,
                jira_project_key=project_key,
                knowledge_base_id=kb.kb_id,
                knowledge_base_name=kb.name,
                started=started,
            )
            return _persist(snapshot), build_knowledge_prompt_context(snapshot)

        collections = [item for item in service.list_collections(kb.kb_id) if not item.archived]
        roles = classify_collection_roles(collections)
        queries = build_retrieval_queries(
            ticket=ticket,
            requirement_context=requirement_context,
            collection_roles=roles,
        )
        deduplicated: dict[tuple[str, str, int, int], dict] = {}
        for query in queries:
            response = service.search(
                kb.kb_id,
                SearchRequest(
                    query=query.query,
                    top_k=top_k_per_query(),
                    collection_id=query.collection_id,
                    active_only=True,
                ),
            )
            for result in response.results:
                key = (
                    result.collection_id,
                    result.document_id,
                    result.version,
                    result.chunk_index,
                )
                row = deduplicated.get(key)
                if row is None:
                    deduplicated[key] = {
                        "result": result,
                        "categories": [query.category],
                    }
                else:
                    if query.category not in row["categories"]:
                        row["categories"].append(query.category)
                    if result.score > row["result"].score:
                        row["result"] = result

        threshold = minimum_score()
        ordered = sorted(
            (
                row for row in deduplicated.values()
                if threshold is None or row["result"].score >= threshold
            ),
            key=lambda row: (
                -row["result"].score,
                row["result"].collection_id,
                row["result"].document_id,
                row["result"].version,
                row["result"].chunk_index,
            ),
        )[:max_retrieved_references()]

        references: list[KnowledgeSnapshotReference] = []
        selected_count = 0
        selected_chars = 0
        document_cache: dict[str, object] = {}
        shadow = knowledge_retrieval_shadow_mode()
        for index, row in enumerate(ordered, start=1):
            result = row["result"]
            if result.document_id not in document_cache:
                try:
                    document_cache[result.document_id] = service.get_document(
                        kb.kb_id, result.document_id
                    )
                except Exception:
                    document_cache[result.document_id] = None
            document = document_cache[result.document_id]
            excerpt = result.content.strip()
            selected = (
                selected_count < max_selected_references()
                and selected_chars + len(excerpt) <= max_context_characters()
            )
            if selected:
                selected_count += 1
                selected_chars += len(excerpt)
            source_type = getattr(document, "source_type", "UNKNOWN") if document else "UNKNOWN"
            title = getattr(document, "title", result.document_id) if document else result.document_id
            references.append(
                KnowledgeSnapshotReference(
                    reference_id=f"REF-{index:03d}",
                    source_result_id=_source_result_id(
                        kb.kb_id,
                        result.collection_id,
                        result.document_id,
                        result.version,
                        result.chunk_index,
                    ),
                    kb_id=kb.kb_id,
                    collection_id=result.collection_id,
                    document_id=result.document_id,
                    document_version=result.version,
                    chunk_index=result.chunk_index,
                    content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                    excerpt=excerpt,
                    title=title,
                    citation=result.source_citation,
                    score=result.score,
                    confidence=result.confidence,
                    authority=_authority(row["categories"][0], result.collection_id),
                    source_type=source_type,
                    matched_query_categories=sorted(row["categories"]),
                    selected=selected,
                    used_in_prompt=selected and not shadow,
                )
            )

        if not references:
            status = KnowledgeRetrievalStatus.NO_MATCHES
            message = (
                f'Knowledge Base "{kb.kb_id}" was searched, but no relevant '
                "references met the selection criteria."
            )
        elif shadow:
            status = KnowledgeRetrievalStatus.COMPLETED_WITH_WARNINGS
            message = "Knowledge retrieval completed in shadow mode and was not included in Analysis."
        else:
            status = KnowledgeRetrievalStatus.COMPLETED
            message = "Knowledge retrieval completed and selected references were included in Analysis."
        snapshot = KnowledgeRetrievalSnapshot(
            snapshot_id=create_snapshot_id(),
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            jira_issue_key=issue_key,
            jira_project_key=project_key,
            knowledge_base_id=kb.kb_id,
            knowledge_base_name=kb.name,
            status=status,
            status_message=message,
            created_at=utc_now_iso(),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            queries=queries,
            retrieved_count=len(references),
            selected_count=sum(item.selected for item in references),
            references=references,
            warnings=(
                ["Retrieval shadow mode is enabled; references were not used in the prompt."]
                if shadow else []
            ),
        )
        _persist(snapshot)
        _sync_review_artifacts(snapshot)
        return snapshot, build_knowledge_prompt_context(snapshot)
    except Exception:
        logger.exception(
            "knowledge_retrieval_failed ticket_id=%s jira_project_key=%s",
            ticket_id,
            project_key,
        )
        snapshot = _status_snapshot(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            status=KnowledgeRetrievalStatus.FAILED,
            message="Knowledge retrieval failed due to an internal search error. Analysis ran without Knowledge context.",
            jira_issue_key=issue_key,
            jira_project_key=project_key,
            started=started,
            failure_reason="internal_search_error",
        )
        return _persist(snapshot), build_knowledge_prompt_context(snapshot)
