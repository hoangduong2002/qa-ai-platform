from __future__ import annotations

import json

import jsonlines
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from filelock import FileLock

from app.services.automatic_knowledge_context.models import KnowledgeRetrievalStatus
from app.services.automatic_knowledge_context.service import prepare_knowledge_context
from knowledge.api import router as api_router
from knowledge.api import ui_router
from knowledge.domain.errors import (
    KnowledgeConflictError,
    KnowledgeDeletionError,
    KnowledgeNotFoundError,
    KnowledgeValidationError,
)
from knowledge.domain.models import SearchRequest
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _service_with_data(tmp_path) -> KnowledgeServiceFacade:
    requirements_root = tmp_path / "requirements"
    snapshot = requirements_root / "QA-1" / "knowledge" / "snapshots" / "snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            {
                "ticket_id": "QA-1",
                "knowledge_base_id": "kb-delete",
                "references": [{"content": "historical evidence"}],
            }
        ),
        encoding="utf-8",
    )
    service = KnowledgeServiceFacade(
        tmp_path / "knowledge",
        requirements_root=requirements_root,
    )
    service.create_kb(
        "kb-delete",
        "Delete Me",
        "",
        "tester",
        jira_project_keys=["QA"],
    )
    service.create_collection(
        "kb-delete", "rules", "Rules", "", 100, "tester"
    )
    service.upload_document(
        kb_id="kb-delete",
        collection_id="rules",
        document_id="rule-01",
        title="Rule",
        source_type="test",
        external_id=None,
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"Requirement rule",
        extension=".txt",
        actor="tester",
    )
    return service


def test_delete_removes_operational_data_and_preserves_historical_snapshot(tmp_path) -> None:
    service = _service_with_data(tmp_path)
    snapshot = (
        tmp_path
        / "requirements"
        / "QA-1"
        / "knowledge"
        / "snapshots"
        / "snapshot.json"
    )

    result = service.delete_kb(
        "kb-delete",
        confirmation="kb-delete",
        actor="qa-lead",
    )

    assert result.deleted_document_count == 1
    assert result.deleted_collection_count == 1
    assert result.released_jira_project_keys == ["QA"]
    assert result.historical_snapshot_count == 1
    assert snapshot.exists()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["references"]
    assert not (tmp_path / "knowledge" / "kb-delete").exists()
    assert service.resolve_kb_by_jira_project_key("QA") is None

    service.create_kb("kb-new", "New", "", "tester", jira_project_keys=["QA"])
    assert service.resolve_kb_by_jira_project_key("QA").kb_id == "kb-new"


def test_delete_empty_kb_leaves_unrelated_kb_unchanged(tmp_path) -> None:
    service = KnowledgeServiceFacade(tmp_path / "knowledge")
    service.create_kb("empty-kb", "Empty", "", "tester")
    service.create_kb(
        "other-kb", "Other", "", "tester", jira_project_keys=["OTHER"]
    )

    result = service.delete_kb(
        "empty-kb", confirmation="empty-kb", actor="tester"
    )

    assert result.deleted_document_count == 0
    assert result.deleted_collection_count == 0
    assert [kb.kb_id for kb in service.list_kbs()] == ["other-kb"]
    assert service.get_kb("other-kb").name == "Other"


def test_delete_counts_multiple_collections(tmp_path) -> None:
    service = KnowledgeServiceFacade(tmp_path / "knowledge")
    service.create_kb("multi-kb", "Multi", "", "tester")
    service.create_collection("multi-kb", "first", "First", "", 100, "tester")
    service.create_collection("multi-kb", "second", "Second", "", 100, "tester")

    result = service.delete_kb(
        "multi-kb", confirmation="multi-kb", actor="tester"
    )

    assert result.deleted_collection_count == 2
    assert result.deleted_document_count == 0


@pytest.mark.parametrize(
    "unsafe_id",
    ["", ".", "..", "../other-kb", r"..\other-kb", "C:\\knowledge"],
)
def test_delete_rejects_unsafe_ids(tmp_path, unsafe_id: str) -> None:
    service = KnowledgeServiceFacade(tmp_path / "knowledge")
    with pytest.raises(KnowledgeValidationError):
        service.delete_kb(unsafe_id, confirmation=unsafe_id, actor="tester")


def test_delete_requires_exact_confirmation_and_is_not_idempotent(tmp_path) -> None:
    service = _service_with_data(tmp_path)

    with pytest.raises(KnowledgeValidationError):
        service.delete_kb("kb-delete", confirmation="Delete Me", actor="tester")

    service.delete_kb("kb-delete", confirmation="kb-delete", actor="tester")
    with pytest.raises(KnowledgeNotFoundError):
        service.delete_kb("kb-delete", confirmation="kb-delete", actor="tester")


def test_delete_is_blocked_while_an_operation_lock_is_held(tmp_path) -> None:
    service = _service_with_data(tmp_path)
    lock_path = service.storage.operation_locks_dir / "kb-delete.lock"

    with FileLock(str(lock_path)):
        with pytest.raises(KnowledgeConflictError, match="active operation"):
            service.delete_kb(
                "kb-delete",
                confirmation="kb-delete",
                actor="tester",
            )

    assert service.get_kb("kb-delete").kb_id == "kb-delete"


def test_deletion_audit_survives_hard_delete(tmp_path) -> None:
    service = _service_with_data(tmp_path)
    service.delete_kb("kb-delete", confirmation="kb-delete", actor="qa-lead")

    audit_path = (
        tmp_path
        / "knowledge"
        / "_config"
        / "deletion_audit"
        / "kb-delete"
        / "audit.jsonl"
    )
    with jsonlines.open(audit_path) as reader:
        events = list(reader)

    assert any(row["event"] == "kb_created" for row in events)
    deleted = [row for row in events if row["event"] == "kb_deleted"][0]
    assert deleted["actor"] == "qa-lead"
    assert deleted["released_jira_project_keys"] == ["QA"]


def test_deleted_kb_search_does_not_recreate_directory(tmp_path) -> None:
    service = _service_with_data(tmp_path)
    service.delete_kb("kb-delete", confirmation="kb-delete", actor="tester")

    with pytest.raises(KnowledgeNotFoundError):
        service.search("kb-delete", SearchRequest(query="rule"))

    assert not (tmp_path / "knowledge" / "kb-delete").exists()


def test_requirement_retrieval_falls_back_after_mapped_kb_is_deleted(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_SHADOW_MODE", "false")
    service = _service_with_data(tmp_path)
    ticket_dir = tmp_path / "requirements" / "QA-2"
    ticket_dir.mkdir(parents=True)
    (ticket_dir / "ticket.json").write_text(
        json.dumps(
            {
                "ticket_id": "QA-2",
                "jira_key": "QA-2",
                "jira_project_key": "QA",
                "source_type": "jira",
                "summary": "Continue without deleted KB",
            }
        ),
        encoding="utf-8",
    )
    service.delete_kb("kb-delete", confirmation="kb-delete", actor="tester")

    snapshot, prompt = prepare_knowledge_context(
        ticket_id="QA-2",
        analysis_run_id="AR-AFTER-DELETE",
        requirement_context="Continue requirement processing.",
        knowledge_service=service,
    )

    assert snapshot.status == KnowledgeRetrievalStatus.NO_MAPPING
    assert snapshot.knowledge_base_id is None
    assert "No Knowledge Base references" in prompt


def test_locked_file_failure_is_safe_and_audited(monkeypatch, tmp_path) -> None:
    service = _service_with_data(tmp_path)

    def fail_cleanup(_path, attempts=5):
        raise PermissionError("C:\\private\\locked-index.db")

    monkeypatch.setattr(service.storage, "_remove_tree_with_retry", fail_cleanup)

    with pytest.raises(KnowledgeDeletionError) as raised:
        service.delete_kb(
            "kb-delete", confirmation="kb-delete", actor="tester"
        )

    assert "locked-index.db" not in str(raised.value)
    audit_path = (
        tmp_path
        / "knowledge"
        / "_config"
        / "deletion_audit"
        / "kb-delete"
        / "audit.jsonl"
    )
    with jsonlines.open(audit_path) as reader:
        assert any(row["event"] == "kb_deletion_failed" for row in reader)


def _api_client(monkeypatch, service: KnowledgeServiceFacade) -> TestClient:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "secret")
    monkeypatch.setattr(api_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(api_router.router)
    return TestClient(app)


def test_delete_api_authorization_confirmation_and_repeat(monkeypatch, tmp_path) -> None:
    service = _service_with_data(tmp_path)
    client = _api_client(monkeypatch, service)

    assert client.request(
        "DELETE",
        "/api/knowledge/bases/kb-delete",
        json={"confirmation": "kb-delete"},
    ).status_code == 403
    assert client.request(
        "DELETE",
        "/api/knowledge/bases/kb-delete",
        headers={"X-Maintainer-Token": "secret"},
        json={"confirmation": "wrong"},
    ).status_code == 400

    deleted = client.request(
        "DELETE",
        "/api/knowledge/bases/kb-delete",
        headers={"X-Maintainer-Token": "secret"},
        json={"confirmation": "kb-delete"},
    )
    repeated = client.request(
        "DELETE",
        "/api/knowledge/bases/kb-delete",
        headers={"X-Maintainer-Token": "secret"},
        json={"confirmation": "kb-delete"},
    )

    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert repeated.status_code == 404


def test_delete_api_returns_conflict_for_active_operation(monkeypatch, tmp_path) -> None:
    service = _service_with_data(tmp_path)
    client = _api_client(monkeypatch, service)
    lock_path = service.storage.operation_locks_dir / "kb-delete.lock"

    with FileLock(str(lock_path)):
        response = client.request(
            "DELETE",
            "/api/knowledge/bases/kb-delete",
            headers={"X-Maintainer-Token": "secret"},
            json={"confirmation": "kb-delete"},
        )

    assert response.status_code == 409
    assert "active operation" in response.json()["detail"]


def test_delete_api_reports_storage_failure_without_internal_path(
    monkeypatch, tmp_path
) -> None:
    service = _service_with_data(tmp_path)
    client = _api_client(monkeypatch, service)

    def fail_cleanup(_path, attempts=5):
        raise PermissionError("C:\\private\\locked-index.db")

    monkeypatch.setattr(service.storage, "_remove_tree_with_retry", fail_cleanup)
    response = client.request(
        "DELETE",
        "/api/knowledge/bases/kb-delete",
        headers={"X-Maintainer-Token": "secret"},
        json={"confirmation": "kb-delete"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Knowledge Base deletion could not be completed safely."
    )
    assert "private" not in response.text
    assert "locked-index" not in response.text


def test_portal_shows_impact_and_deletes_with_maintainer_token(
    monkeypatch, tmp_path
) -> None:
    service = _service_with_data(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "secret")
    monkeypatch.setattr(ui_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(ui_router.router)
    client = TestClient(app)

    page = client.get("/portal/kb/kb-delete")
    assert page.status_code == 200
    assert "Delete Knowledge Base" in page.text
    assert "1 documents will be deleted" in page.text
    assert "historical Knowledge" in page.text

    denied = client.post(
        "/portal/kb/kb-delete/delete",
        data={
            "confirmation": "kb-delete",
            "maintainer_token_value": "wrong",
        },
    )
    assert denied.status_code == 403
    assert service.get_kb("kb-delete").kb_id == "kb-delete"

    deleted = client.post(
        "/portal/kb/kb-delete/delete",
        data={
            "confirmation": "kb-delete",
            "maintainer_token_value": "secret",
        },
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    assert "was deleted" in deleted.text


def test_portal_hides_delete_action_without_maintainer_configuration(
    monkeypatch, tmp_path
) -> None:
    service = _service_with_data(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.delenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", raising=False)
    monkeypatch.setattr(ui_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(ui_router.router)

    page = TestClient(app).get("/portal/kb/kb-delete")

    assert page.status_code == 200
    assert 'id="open-kb-delete"' not in page.text
    assert 'id="kb-delete-dialog"' not in page.text
