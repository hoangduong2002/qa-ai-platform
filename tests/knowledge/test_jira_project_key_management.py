from __future__ import annotations

import json
from html import unescape
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge.api import router as api_router
from knowledge.api import ui_router
from knowledge.domain.errors import KnowledgeConflictError, KnowledgeValidationError
from knowledge.services.jira_project_keys import (
    normalize_jira_project_key,
    normalize_jira_project_keys,
)
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _service(tmp_path: Path) -> KnowledgeServiceFacade:
    return KnowledgeServiceFacade(tmp_path / "knowledge_bases")


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, KnowledgeServiceFacade]:
    service = _service(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "maintainer")
    monkeypatch.setattr(api_router, "get_knowledge_service", lambda: service)
    monkeypatch.setattr(ui_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(api_router.router)
    app.include_router(ui_router.router)
    return TestClient(app), service


def test_normalizes_deduplicates_and_validates_project_keys() -> None:
    assert normalize_jira_project_key(" wec ") == "WEC"
    assert normalize_jira_project_keys([" wec ", "WecDev", "WEC", "qa_2"]) == [
        "WEC",
        "WECDEV",
        "QA_2",
    ]
    for value in ["", "   ", "-WEC", "WEC PROJECT", "WEC/DEV"]:
        with pytest.raises(KnowledgeValidationError, match="Invalid Jira project key"):
            normalize_jira_project_key(value)


def test_create_persists_optional_normalized_keys_and_prevents_conflicts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    created = service.create_kb(
        "weclever",
        "WeClever",
        "Knowledge",
        "tester",
        jira_project_keys=[" wec ", "WecDev", "WEC"],
    )
    without_keys = service.create_kb("legacy-style", "Legacy", "", "tester")

    assert created.jira_project_keys == ["WEC", "WECDEV"]
    assert without_keys.jira_project_keys == []
    metadata = json.loads(
        (tmp_path / "knowledge_bases" / "weclever" / "knowledge_base.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["jira_project_keys"] == ["WEC", "WECDEV"]

    with pytest.raises(KnowledgeConflictError) as conflict:
        service.create_kb(
            "weclever-old",
            "Old",
            "",
            "tester",
            jira_project_keys=["wec"],
        )
    assert str(conflict.value) == (
        'Jira project key "WEC" is already assigned to Knowledge Base "weclever".'
    )
    assert not (tmp_path / "knowledge_bases" / "weclever-old").exists()


def test_invalid_create_does_not_leave_partial_kb(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(KnowledgeValidationError):
        service.create_kb(
            "invalid-kb",
            "Invalid",
            "",
            "tester",
            jira_project_keys=["WEC DEV"],
        )
    assert not (tmp_path / "knowledge_bases" / "invalid-kb").exists()


def test_update_adds_replaces_removes_and_preserves_on_conflict(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_kb("one", "One", "original", "tester", jira_project_keys=["ONE"])
    service.create_kb("two", "Two", "", "tester", jira_project_keys=["TWO"])

    retained = service.update_kb("one", {"jira_project_keys": ["one", "ONEDEV"]}, "tester")
    assert retained.jira_project_keys == ["ONE", "ONEDEV"]
    assert retained.description == "original"

    with pytest.raises(KnowledgeConflictError):
        service.update_kb("one", {"jira_project_keys": ["TWO"]}, "tester")
    unchanged = service.get_kb("one")
    assert unchanged.jira_project_keys == ["ONE", "ONEDEV"]
    assert unchanged.description == "original"

    removed = service.update_kb("one", {"jira_project_keys": []}, "tester")
    assert removed.jira_project_keys == []


def test_lookup_normalizes_unknown_and_legacy_metadata(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_kb("mapped", "Mapped", "", "tester", jira_project_keys=["WEC", "WECDEV"])
    service.create_kb("legacy", "Legacy", "", "tester")
    legacy_file = tmp_path / "knowledge_bases" / "legacy" / "knowledge_base.json"
    legacy_payload = json.loads(legacy_file.read_text(encoding="utf-8"))
    legacy_payload.pop("jira_project_keys")
    legacy_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    assert service.resolve_kb_by_jira_project_key(" wec ").kb_id == "mapped"
    assert service.resolve_kb_by_jira_project_key("wecdev").kb_id == "mapped"
    assert service.resolve_kb_by_jira_project_key("UNKNOWN") is None
    assert service.get_kb("legacy").jira_project_keys == []
    with pytest.raises(KnowledgeValidationError):
        service.resolve_kb_by_jira_project_key("WEC DEV")


def test_rest_create_update_resolve_and_form_backward_compatibility(tmp_path: Path, monkeypatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    headers = {"X-Maintainer-Token": "maintainer"}
    created = client.post(
        "/api/knowledge/bases",
        headers=headers,
        json={
            "kb_id": "weclever",
            "name": "WeClever",
            "description": "Knowledge",
            "jira_project_keys": ["wec", "WECDEV"],
        },
    )
    legacy_form = client.post(
        "/api/knowledge/bases",
        headers=headers,
        data={"kb_id": "legacy", "name": "Legacy"},
    )
    updated = client.patch(
        "/api/knowledge/bases/weclever",
        headers=headers,
        json={"jira_project_keys": ["WEC", "WECSUP"]},
    )

    assert created.status_code == 200
    assert created.json()["jira_project_keys"] == ["WEC", "WECDEV"]
    assert legacy_form.status_code == 200
    assert legacy_form.json()["jira_project_keys"] == []
    assert updated.status_code == 200
    assert updated.json()["jira_project_keys"] == ["WEC", "WECSUP"]

    resolved = client.get("/api/knowledge/bases/resolve", params={"jira_project_key": " wecsup "})
    removed = client.get("/api/knowledge/bases/resolve", params={"jira_project_key": "WECDEV"})
    unknown = client.get("/api/knowledge/bases/resolve", params={"jira_project_key": "UNKNOWN"})
    invalid = client.get("/api/knowledge/bases/resolve", params={"jira_project_key": "WEC DEV"})
    assert resolved.json() == {
        "jira_project_key": "WECSUP",
        "resolved": True,
        "knowledge_base": {
            "kb_id": "weclever",
            "name": "WeClever",
            "jira_project_keys": ["WEC", "WECSUP"],
        },
    }
    assert removed.json()["resolved"] is False
    assert unknown.status_code == 200 and unknown.json()["knowledge_base"] is None
    assert invalid.status_code == 400
    assert service.get_kb("weclever").description == "Knowledge"


def test_rest_conflict_returns_409(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    headers = {"X-Maintainer-Token": "maintainer"}
    assert client.post(
        "/api/knowledge/bases",
        headers=headers,
        json={"kb_id": "one", "name": "One", "jira_project_keys": ["WEC"]},
    ).status_code == 200
    conflict = client.post(
        "/api/knowledge/bases",
        headers=headers,
        json={"kb_id": "two", "name": "Two", "jira_project_keys": ["wec"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        'Jira project key "WEC" is already assigned to Knowledge Base "one".'
    )


def test_portal_create_edit_and_specific_error_messages(tmp_path: Path, monkeypatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    created = client.post(
        "/portal/kb",
        data={
            "kb_id": "weclever",
            "name": "WeClever",
            "jira_project_keys": "wec, WecDev",
            "maintainer_token_value": "maintainer",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "WECDEV" in created.text
    assert service.get_kb("weclever").jira_project_keys == ["WEC", "WECDEV"]

    edited = client.post(
        "/portal/kb/weclever/jira-project-keys",
        data={"jira_project_keys": "WEC, WECSUP", "maintainer_token_value": "maintainer"},
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert service.get_kb("weclever").jira_project_keys == ["WEC", "WECSUP"]

    invalid = client.post(
        "/portal/kb",
        data={
            "kb_id": "invalid",
            "name": "Invalid",
            "jira_project_keys": "WEC DEV",
            "maintainer_token_value": "maintainer",
        },
    )
    wrong_token = client.post(
        "/portal/kb",
        data={
            "kb_id": "denied",
            "name": "Denied",
            "jira_project_keys": "NEW",
            "maintainer_token_value": "wrong",
        },
        follow_redirects=True,
    )
    duplicate = client.post(
        "/portal/kb",
        data={
            "kb_id": "duplicate",
            "name": "Duplicate",
            "jira_project_keys": "WEC",
            "maintainer_token_value": "maintainer",
        },
    )
    assert invalid.status_code == 400
    assert 'Invalid Jira project key "WEC DEV".' in unescape(invalid.text)
    assert "Maintainer access" not in invalid.text
    assert wrong_token.status_code == 200
    assert "Maintainer access is required" in wrong_token.text
    assert duplicate.status_code == 409
    assert "already assigned to Knowledge Base" in duplicate.text
