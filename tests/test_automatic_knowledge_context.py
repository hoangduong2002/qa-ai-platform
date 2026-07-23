from __future__ import annotations

import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.automatic_knowledge_context.artifacts import (
    load_latest_snapshot,
    load_snapshot,
)
from app.services.automatic_knowledge_context.models import KnowledgeRetrievalStatus
from app.services.automatic_knowledge_context.query_builder import (
    build_retrieval_queries,
)
from app.services.automatic_knowledge_context.service import prepare_knowledge_context
from app.services.jira_project_key_service import extract_jira_project_key
from app.services.knowledge_reference_review.artifacts import save_review_records
from knowledge.domain.models import SearchResponse, SearchResult
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _write_ticket(tmp_path: Path, payload: dict) -> None:
    directory = tmp_path / "requirements" / payload["ticket_id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ticket.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


class _KnowledgeService:
    def __init__(
        self,
        *,
        mapped: bool = True,
        ready: bool = True,
        fail_search: bool = False,
        results: list[SearchResult] | None = None,
    ):
        self.mapped = mapped
        self.ready = ready
        self.fail_search = fail_search
        self.results = results or []
        self.search_kb_ids: list[str] = []

    def resolve_kb_by_jira_project_key(self, project_key: str):
        if not self.mapped:
            return None
        return SimpleNamespace(
            kb_id="weclever",
            name="WeClever Knowledge Base",
            enabled=True,
        )

    def kb_health(self, kb_id: str):
        return {"index_exists": self.ready}

    def list_collections(self, kb_id: str):
        return [
            SimpleNamespace(
                collection_id="business-rules",
                name="Business Rules",
                description="Approved domain behavior",
                priority=1,
                archived=False,
            ),
            SimpleNamespace(
                collection_id="defects",
                name="Historical Defects",
                description="Previous defects",
                priority=20,
                archived=False,
            ),
        ]

    def search(self, kb_id: str, request):
        self.search_kb_ids.append(kb_id)
        if self.fail_search:
            raise RuntimeError("private storage failure")
        return SearchResponse(
            query=request.query,
            took_ms=1,
            total=len(self.results),
            results=self.results[: request.top_k],
        )

    def get_document(self, kb_id: str, document_id: str):
        return SimpleNamespace(title=f"Title {document_id}", source_type="knowledge-package")


def _result(document_id: str, chunk_index: int, content: str, score: float):
    return SearchResult(
        kb_id="weclever",
        collection_id="business-rules",
        document_id=document_id,
        version=2,
        chunk_index=chunk_index,
        content=content,
        confidence=0.9,
        score=score,
        explanation="",
        source_citation=f"{document_id}:v2:chunk{chunk_index}",
    )


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_SHADOW_MODE", "false")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERIES", "5")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_TOP_K", "5")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_RESULTS", "30")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_SELECTED", "10")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_CONTEXT_CHARS", "12000")
    monkeypatch.delenv("KNOWLEDGE_AUTO_RETRIEVAL_MIN_SCORE", raising=False)


def test_jira_project_extraction_prefers_project_and_has_safe_fallback() -> None:
    assert extract_jira_project_key(
        {"fields": {"project": {"key": "wec"}}},
        "OTHER-123",
    ) == "WEC"
    assert extract_jira_project_key({}, "WecDev-42") == "WECDEV"
    assert extract_jira_project_key({}, "NOSEPARATOR") is None
    assert extract_jira_project_key({}, "-100") is None


def test_query_builder_is_deterministic_bounded_and_uses_requirement_content(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERIES", "3")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERY_CHARS", "80")
    ticket = {
        "summary": "Use CMU price for HBLD090",
        "issue_type": "Story",
        "components": ["Pricing API"],
        "labels": ["insurance"],
    }
    context = "Acceptance criteria: C2S patients use CMU instead of AMO reimbursement."
    first = build_retrieval_queries(ticket=ticket, requirement_context=context)
    second = build_retrieval_queries(ticket=ticket, requirement_context=context)
    assert first == second
    assert 1 <= len(first) <= 3
    assert all(len(item.query) <= 80 for item in first)
    combined = " ".join(item.query for item in first)
    assert "cmu" in combined.lower()
    assert "HBLD090" in combined
    assert "C2S" in combined
    assert "pricing" in combined.lower()


def test_automatic_retrieval_deduplicates_persists_and_builds_prompt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-1234",
            "jira_key": "WEC-1234",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "Use CMU price for HBLD090",
            "issue_type": "Story",
        },
    )
    duplicate = _result(
        "cmu-pricing",
        1,
        "HBLD090 uses the CMU unit price for C2S patients.",
        4.2,
    )
    service = _KnowledgeService(results=[duplicate, duplicate])
    snapshot, prompt = prepare_knowledge_context(
        ticket_id="WEC-1234",
        analysis_run_id="AR-TEST-1",
        requirement_context="C2S CMU HBLD090 AMO reimbursement acceptance criteria",
        knowledge_service=service,
    )

    assert snapshot.status == KnowledgeRetrievalStatus.COMPLETED
    assert snapshot.knowledge_base_id == "weclever"
    assert snapshot.retrieved_count == 1
    assert snapshot.selected_count == 1
    assert len(snapshot.references) == 1
    assert snapshot.references[0].reference_id == "REF-001"
    assert snapshot.references[0].used_in_prompt is True
    assert "[REF-001]" in prompt
    assert "AUTHORITATIVE KNOWLEDGE" in prompt
    assert "HBLD090 uses the CMU unit price" in prompt
    assert set(service.search_kb_ids) == {"weclever"}

    stored = load_latest_snapshot("WEC-1234")
    assert stored.snapshot_id == snapshot.snapshot_id
    assert load_snapshot("WEC-1234", snapshot.snapshot_id).analysis_run_id == "AR-TEST-1"
    ticket = json.loads(
        (tmp_path / "requirements" / "WEC-1234" / "ticket.json").read_text(encoding="utf-8")
    )
    assert ticket["knowledge_base_id"] == "weclever"
    assert ticket["knowledge_snapshot_id"] == snapshot.snapshot_id


def test_real_published_kb_resolves_and_retrieves_for_wec_scenario(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb(
        "weclever",
        "WeClever Knowledge Base",
        "",
        "tester",
        jira_project_keys=["WEC"],
    )
    service.create_collection(
        "weclever",
        "business-rules",
        "Business Rules",
        "Approved rules",
        1,
        "tester",
    )
    service.upload_document(
        kb_id="weclever",
        collection_id="business-rules",
        document_id="cmu-pricing",
        title="CMU Pricing Rules",
        source_type="manual",
        external_id=None,
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=(
            b"For C2S patients, Inlay Core HBLD090 must use the CMU unit price "
            b"instead of the AMO reimbursement base."
        ),
        extension=".md",
        actor="tester",
    )
    service.publish_document("weclever", "cmu-pricing", "tester")
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-1234",
            "jira_key": "WEC-1234",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "Use CMU unit price for Inlay Core HBLD090",
        },
    )
    snapshot, prompt = prepare_knowledge_context(
        ticket_id="WEC-1234",
        analysis_run_id="AR-REAL-KB",
        requirement_context=(
            "For a C2S/CMU patient, HBLD090 must use the CMU unit price "
            "instead of the AMO reimbursement base."
        ),
        knowledge_service=service,
    )
    assert snapshot.status.value == "completed"
    assert snapshot.jira_project_key == "WEC"
    assert snapshot.knowledge_base_id == "weclever"
    assert snapshot.selected_count >= 1
    assert "HBLD090" in prompt
    assert "[REF-001]" in prompt


@pytest.mark.parametrize(
    ("kb_enabled", "retrieval_enabled", "mapped", "ready", "expected"),
    [
        ("false", "true", True, True, "disabled"),
        ("true", "false", True, True, "retrieval_disabled"),
        ("true", "true", False, True, "no_mapping"),
        ("true", "true", True, False, "kb_not_ready"),
    ],
)
def test_fallback_statuses_are_distinct_and_non_fatal(
    tmp_path: Path,
    monkeypatch,
    kb_enabled: str,
    retrieval_enabled: str,
    mapped: bool,
    ready: bool,
    expected: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", kb_enabled)
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_ENABLED", retrieval_enabled)
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-10",
            "jira_key": "WEC-10",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "Requirement",
        },
    )
    snapshot, prompt = prepare_knowledge_context(
        ticket_id="WEC-10",
        analysis_run_id="AR-FALLBACK",
        requirement_context="Requirement content",
        knowledge_service=_KnowledgeService(mapped=mapped, ready=ready),
    )
    assert snapshot.status.value == expected
    assert snapshot.references == []
    assert "No Knowledge Base references" in prompt


def test_no_project_no_matches_and_failure_are_not_conflated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    _write_ticket(
        tmp_path,
        {"ticket_id": "MANUAL-1", "source_type": "manual", "summary": "Manual"},
    )
    no_project, _ = prepare_knowledge_context(
        ticket_id="MANUAL-1",
        analysis_run_id="AR-1",
        requirement_context="Manual content",
        knowledge_service=_KnowledgeService(),
    )
    assert no_project.status.value == "no_project_key"

    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-11",
            "jira_key": "WEC-11",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "No match",
        },
    )
    no_matches, _ = prepare_knowledge_context(
        ticket_id="WEC-11",
        analysis_run_id="AR-2",
        requirement_context="No matching knowledge",
        knowledge_service=_KnowledgeService(results=[]),
    )
    failed, _ = prepare_knowledge_context(
        ticket_id="WEC-11",
        analysis_run_id="AR-3",
        requirement_context="Search failure",
        knowledge_service=_KnowledgeService(fail_search=True),
    )
    assert no_matches.status.value == "no_matches"
    assert failed.status.value == "failed"
    assert failed.failure_reason == "internal_search_error"
    assert "private storage failure" not in failed.status_message


def test_retrieval_respects_score_selection_and_context_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MIN_SCORE", "4.0")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_SELECTED", "2")
    monkeypatch.setenv("KNOWLEDGE_AUTO_RETRIEVAL_MAX_CONTEXT_CHARS", "1000")
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-15",
            "jira_key": "WEC-15",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "CMU price",
        },
    )
    service = _KnowledgeService(
        results=[
            _result("high-one", 1, "A" * 700, 6.0),
            _result("high-two", 1, "B" * 700, 5.0),
            _result("below-threshold", 1, "C" * 100, 3.0),
        ]
    )
    snapshot, prompt = prepare_knowledge_context(
        ticket_id="WEC-15",
        analysis_run_id="AR-LIMITS",
        requirement_context="CMU pricing rules",
        knowledge_service=service,
    )
    assert snapshot.retrieved_count == 2
    assert snapshot.selected_count == 1
    assert snapshot.references[0].used_in_prompt is True
    assert snapshot.references[1].used_in_prompt is False
    assert "A" * 100 in prompt
    assert "B" * 100 not in prompt
    assert all(item.document_id != "below-threshold" for item in snapshot.references)


def test_reviewed_rerun_clones_snapshot_and_preserves_original(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "WEC-12",
            "jira_key": "WEC-12",
            "jira_project_key": "WEC",
            "source_type": "jira",
            "summary": "CMU HBLD090",
        },
    )
    service = _KnowledgeService(
        results=[
            _result("rule-one", 1, "First rule.", 5.0),
            _result("rule-two", 2, "Second rule.", 4.0),
        ]
    )
    original, _ = prepare_knowledge_context(
        ticket_id="WEC-12",
        analysis_run_id="AR-ORIGINAL",
        requirement_context="CMU HBLD090",
        knowledge_service=service,
    )
    first, second = original.references
    save_review_records(
        "WEC-12",
        [
            {
                "source_result_id": first.source_result_id,
                "classification": "REJECTED",
            },
            {
                "source_result_id": second.source_result_id,
                "classification": "ACCEPTED",
            },
        ],
    )

    reviewed, prompt = prepare_knowledge_context(
        ticket_id="WEC-12",
        analysis_run_id="AR-REVIEWED",
        requirement_context="CMU HBLD090",
        use_reviewed_references=True,
        adjusted_by="qa.user",
    )
    assert reviewed.snapshot_id != original.snapshot_id
    assert reviewed.based_on_snapshot_id == original.snapshot_id
    assert reviewed.selection_mode == "reviewed"
    assert reviewed.adjusted_by == "qa.user"
    assert next(item for item in reviewed.references if item.source_result_id == first.source_result_id).used_in_prompt is False
    assert "First rule." not in prompt
    assert "Second rule." in prompt
    assert load_snapshot("WEC-12", original.snapshot_id).analysis_run_id == "AR-ORIGINAL"


def test_analysis_prompt_receives_prepared_knowledge_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    node = importlib.import_module("graph.nodes.analyze_requirement")
    captured = {}
    monkeypatch.setattr(
        node,
        "load_prompt",
        lambda path: "Requirement:\n{requirement_context}\nKnowledge:\n{knowledge_context}",
    )
    monkeypatch.setattr(
        node,
        "call_text_llm",
        lambda **kwargs: captured.setdefault(
            "prompt",
            kwargs["prompt"],
        ) and json.dumps(
            {
                "actors": [],
                "functional_requirements": ["Use CMU [REF-001]"],
                "business_rules": [],
                "validations": [],
                "dependencies": [],
                "risks": [],
                "missing_information": [],
                "requirement_items": [],
            }
        ),
    )
    monkeypatch.setattr(
        node,
        "resolve_provider_for_task",
        lambda *args, **kwargs: {"provider": "test", "ai_mode": "test", "model": "test"},
    )
    monkeypatch.setattr(node, "run_structured_requirement_analysis_shadow", lambda state: {})
    monkeypatch.setattr(
        node,
        "run_requirement_quality_gate",
        lambda **kwargs: {"quality_report": {}},
    )

    result = node.analyze_requirement(
        {
            "ticket_id": "WEC-20",
            "requirement_context": "Jira says to use CMU.",
            "knowledge_context": (
                "AUTHORITATIVE KNOWLEDGE\n"
                "[REF-001]\n"
                "HBLD090 uses the CMU unit price."
            ),
        }
    )
    assert "Jira says to use CMU." in captured["prompt"]
    assert "[REF-001]" in captured["prompt"]
    assert "HBLD090 uses the CMU unit price." in captured["prompt"]
    assert result["analysis"]["functional_requirements"] == ["Use CMU [REF-001]"]


def test_jira_import_orchestrator_runs_analysis_without_review(monkeypatch) -> None:
    workflow = importlib.import_module("app.services.requirement_workflow_service")
    calls = []
    monkeypatch.setattr(
        workflow,
        "create_requirement_from_jira_and_sanitize",
        lambda **kwargs: calls.append(("create", kwargs["issue_key"])) or "WEC-1234",
    )
    monkeypatch.setattr(
        workflow,
        "_run_requirement_questions_sync",
        lambda **kwargs: calls.append(("analyze", kwargs["ticket_id"])) or {},
    )
    result = workflow.create_jira_requirement_and_run_analysis(
        issue_key="WEC-1234",
        ai_mode="TEST_LOCAL_ONLY",
    )
    assert result == "WEC-1234"
    assert calls == [("create", "WEC-1234"), ("analyze", "WEC-1234")]


def test_jira_import_to_automatic_retrieval_to_analysis_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    workflow = importlib.import_module("app.services.requirement_workflow_service")
    retrieval = importlib.import_module(
        "app.services.automatic_knowledge_context.service"
    )
    captured = {}

    def create_requirement(**kwargs):
        _write_ticket(
            tmp_path,
            {
                "ticket_id": "WEC-1234",
                "jira_key": "WEC-1234",
                "jira_project_key": "WEC",
                "source_type": "jira",
                "summary": "Use CMU price for HBLD090",
            },
        )
        return "WEC-1234"

    class Graph:
        def invoke(self, state):
            captured.update(state)
            analysis_dir = tmp_path / "requirements" / "WEC-1234" / "analysis"
            analysis_dir.mkdir(parents=True, exist_ok=True)
            (analysis_dir / "requirement_analysis.json").write_text(
                json.dumps({"business_rules": ["CMU [REF-001]"]}),
                encoding="utf-8",
            )
            return {
                "analysis": {"business_rules": ["CMU [REF-001]"]},
                "clarifications": {},
            }

    monkeypatch.setattr(
        workflow,
        "create_requirement_from_jira_and_sanitize",
        create_requirement,
    )
    monkeypatch.setattr(
        workflow,
        "load_requirement",
        lambda state: {
            "requirement_context": "C2S CMU HBLD090 AMO reimbursement",
            "requirement_context_metadata": {"context_source": "test"},
        },
    )
    monkeypatch.setattr(workflow, "requirement_question_graph", Graph())
    monkeypatch.setattr(
        retrieval,
        "get_knowledge_service",
        lambda: _KnowledgeService(
            results=[
                _result(
                    "cmu-rule",
                    1,
                    "HBLD090 uses the CMU unit price for C2S patients.",
                    5.0,
                )
            ]
        ),
    )

    result = workflow.create_jira_requirement_and_run_analysis(
        issue_key="WEC-1234",
        ai_mode="TEST_LOCAL_ONLY",
    )
    assert result == "WEC-1234"
    assert captured["jira_project_key"] == "WEC"
    assert captured["knowledge_base_id"] == "weclever"
    assert captured["knowledge_retrieval_status"] == "completed"
    assert "[REF-001]" in captured["knowledge_context"]
    assert load_latest_snapshot("WEC-1234").analysis_run_id == captured["analysis_run_id"]
    latest_run = json.loads(
        (
            tmp_path
            / "requirements"
            / "WEC-1234"
            / "analysis"
            / "latest_analysis_run.json"
        ).read_text(encoding="utf-8")
    )
    assert latest_run["knowledge_snapshot_id"] == captured["knowledge_snapshot_id"]
    assert latest_run["status"] == "completed"


def test_review_template_escapes_knowledge_content() -> None:
    portal = importlib.import_module("app.web.portal_router")
    html = portal.templates.get_template("knowledge_reference_review.html").render(
        ticket_id="WEC-1",
        review_dashboard={
            "review_required": False,
            "requests": [],
            "review_count": 0,
            "knowledge_snapshot": None,
            "candidates": [
                {
                    "result_id": "REF-X",
                    "retrieval_need": "test",
                    "jira_issue_being_clarified": "test",
                    "kb_id": "kb",
                    "collection_id": "rules",
                    "document_id": "doc",
                    "version": 1,
                    "chunk_index": 1,
                    "confidence": 1.0,
                    "status": "INDEXED",
                    "effective_from": None,
                    "effective_to": None,
                    "source_type": "manual",
                    "citation": "doc:1",
                    "excerpt": "<script>alert('x')</script>",
                    "review": {},
                }
            ],
        },
        error="",
        success="",
        selected_references=[],
        rejected_references=[],
        knowledge_conflicts=[],
        reference_context="",
    )
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_requirement_portal_and_read_api_show_no_mapping_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _enable(monkeypatch)
    _write_ticket(
        tmp_path,
        {
            "ticket_id": "ABC-100",
            "jira_key": "ABC-100",
            "jira_project_key": "ABC",
            "source_type": "jira",
            "source": "jira",
            "summary": "Unmapped requirement",
        },
    )
    prepare_knowledge_context(
        ticket_id="ABC-100",
        analysis_run_id="AR-NO-MAPPING",
        requirement_context="Unmapped requirement",
        knowledge_service=_KnowledgeService(mapped=False),
    )
    portal = importlib.import_module("app.web.portal_router")
    app = FastAPI()
    app.include_router(portal.router)
    client = TestClient(app)

    page = client.get("/portal/requirements/ABC-100")
    payload = client.get("/portal/requirements/ABC-100/knowledge-references")
    assert page.status_code == 200
    assert "Knowledge Context" in page.text
    assert "ABC" in page.text
    assert "no_mapping" in page.text
    assert "No Knowledge Base is mapped" in page.text
    assert payload.status_code == 200
    assert payload.json()["knowledge"]["status"] == "no_mapping"
