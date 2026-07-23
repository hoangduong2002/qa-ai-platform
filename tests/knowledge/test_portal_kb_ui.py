from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import portal_router
from knowledge.api import router as knowledge_api_router
from knowledge.api import ui_router


@dataclass
class _Record:
    values: dict

    def model_dump(self) -> dict:
        return dict(self.values)


class _KnowledgeService:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []

    def list_kbs(self):
        return [_Record({"kb_id": "qa", "name": "QA", "description": "", "enabled": True})]

    def create_kb(
        self,
        kb_id: str,
        name: str,
        description: str,
        actor: str,
        jira_project_keys=None,
    ):
        self.created.append((kb_id, name, actor))
        return _Record({"kb_id": kb_id, "name": name, "description": description, "enabled": True})


def _ui_client(monkeypatch, service: _KnowledgeService) -> TestClient:
    app = FastAPI()
    app.include_router(ui_router.router)
    monkeypatch.setattr(ui_router, "get_knowledge_service", lambda: service)
    return TestClient(app)


def test_kb_navigation_appears_when_enabled_without_using_knowledge_system_flag(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_ENABLED", "false")
    monkeypatch.setattr(portal_router, "list_requirements", lambda: [])
    app = FastAPI()
    app.include_router(portal_router.router)

    response = TestClient(app).get("/portal")

    assert response.status_code == 200
    assert 'href="/portal/kb"' in response.text


def test_kb_navigation_is_hidden_when_feature_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_ENABLED", "true")
    monkeypatch.setattr(portal_router, "list_requirements", lambda: [])
    app = FastAPI()
    app.include_router(portal_router.router)

    response = TestClient(app).get("/portal")

    assert response.status_code == 200
    assert 'href="/portal/kb"' not in response.text
    assert 'href="/portal/knowledge"' in response.text


def test_kb_route_and_read_only_list_are_accessible_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.delenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", raising=False)
    client = _ui_client(monkeypatch, _KnowledgeService())

    response = client.get("/portal/kb")

    assert response.status_code == 200
    assert "Knowledge Bases" in response.text
    assert "Read-only access" in response.text
    assert "/portal/kb/qa" in response.text


def test_kb_route_returns_explicit_disabled_response(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "false")
    client = _ui_client(monkeypatch, _KnowledgeService())

    response = client.get("/portal/kb")

    assert response.status_code == 404
    assert response.json()["detail"] == "Knowledge Base feature is disabled."


def test_missing_maintainer_access_is_explicit_and_token_is_not_rendered(monkeypatch) -> None:
    token = "private-maintainer-value"
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", token)
    service = _KnowledgeService()
    client = _ui_client(monkeypatch, service)

    page = client.get("/portal/kb")
    denied = client.post(
        "/portal/kb",
        data={"kb_id": "new", "name": "New", "maintainer_token_value": "wrong"},
        follow_redirects=True,
    )

    assert page.status_code == 200
    assert token not in page.text
    assert denied.status_code == 200
    assert "Maintainer access is required" in denied.text
    assert service.created == []


def test_list_api_remains_readable_and_write_api_requires_maintainer(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.delenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", raising=False)
    service = _KnowledgeService()
    monkeypatch.setattr(knowledge_api_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(knowledge_api_router.router)
    client = TestClient(app)

    readable = client.get("/api/knowledge/bases")
    protected = client.post("/api/knowledge/bases", data={"kb_id": "new", "name": "New"})

    assert readable.status_code == 200
    assert readable.json()[0]["kb_id"] == "qa"
    assert protected.status_code == 503
    assert protected.json()["detail"] == "KNOWLEDGE_BASE_MAINTAINER_TOKEN is not configured."
