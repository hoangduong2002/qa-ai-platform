from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge.api import router as api_router
from knowledge.api import ui_router
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _package() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("package/", b"")
        archive.writestr("package/domain/guide.md", "Guide")
    return output.getvalue()


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, KnowledgeServiceFacade]:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "Knowledge", "", "tester")
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "maintainer")
    monkeypatch.setattr(ui_router, "get_knowledge_service", lambda: service)
    monkeypatch.setattr(api_router, "get_knowledge_service", lambda: service)
    app = FastAPI()
    app.include_router(ui_router.router)
    app.include_router(api_router.router)
    return TestClient(app), service


def test_portal_package_forms_render_and_manual_forms_remain(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    response = client.get("/portal/kb/KB1")
    assert response.status_code == 200
    assert "Import Knowledge Package" in response.text
    assert 'action="/portal/kb/KB1/packages/inspect"' in response.text
    assert 'action="/portal/kb/KB1/packages/import"' in response.text
    assert 'webkitdirectory' in response.text
    assert 'action="/portal/kb/KB1/collections"' in response.text
    assert 'action="/portal/kb/KB1/documents/upload"' in response.text


def test_portal_inspect_authorization_and_validation_errors_are_distinct(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    denied = client.post(
        "/portal/kb/KB1/packages/inspect",
        data={"maintainer_token_value": "wrong", "conflict_mode": "skip"},
        files={"zip_file": ("package.zip", _package(), "application/zip")},
    )
    invalid = client.post(
        "/portal/kb/KB1/packages/inspect",
        data={"maintainer_token_value": "maintainer", "conflict_mode": "skip"},
        files={"zip_file": ("package.zip", b"broken", "application/zip")},
    )
    valid = client.post(
        "/portal/kb/KB1/packages/inspect",
        data={"maintainer_token_value": "maintainer", "conflict_mode": "skip"},
        files={"zip_file": ("package.zip", _package(), "application/zip")},
    )
    assert denied.status_code == 403
    assert "Maintainer authorization failed" in denied.text
    assert invalid.status_code == 400
    assert "Package validation failed" in invalid.text
    assert "Maintainer authorization failed" not in invalid.text
    assert valid.status_code == 200
    assert '"collection_count": 1' in valid.text


def test_portal_dry_run_does_not_mutate_and_import_succeeds(tmp_path: Path, monkeypatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    request = {
        "data": {
            "maintainer_token_value": "maintainer",
            "conflict_mode": "skip",
            "dry_run": "true",
        },
        "files": {"zip_file": ("package.zip", _package(), "application/zip")},
    }
    dry_run = client.post("/portal/kb/KB1/packages/import", **request)
    assert dry_run.status_code == 200
    assert service.list_collections("KB1") == []
    assert service.list_documents("KB1") == []

    imported = client.post(
        "/portal/kb/KB1/packages/import",
        data={"maintainer_token_value": "maintainer", "conflict_mode": "skip"},
        files={"zip_file": ("package.zip", _package(), "application/zip")},
    )
    assert imported.status_code == 200
    assert len(service.list_collections("KB1")) == 1
    assert len(service.list_documents("KB1")) == 1


def test_rest_package_routes_use_header_and_support_folder_upload(tmp_path: Path, monkeypatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    denied = client.post(
        "/api/knowledge/bases/KB1/packages/inspect",
        files={"zip_file": ("package.zip", _package(), "application/zip")},
    )
    inspected = client.post(
        "/api/knowledge/bases/KB1/packages/inspect",
        headers={"X-Maintainer-Token": "maintainer"},
        files={"folder_files": ("folder/domain/guide.md", b"Guide", "text/markdown")},
    )
    dry_run = client.post(
        "/api/knowledge/bases/KB1/packages/import",
        headers={"X-Maintainer-Token": "maintainer"},
        data={"dry_run": "true", "conflict_mode": "skip"},
        files={"zip_file": ("package.zip", _package(), "application/zip")},
    )
    assert denied.status_code == 403
    assert inspected.status_code == 200
    assert inspected.json()["collection_count"] == 1
    assert dry_run.status_code == 200
    assert dry_run.json()["status"] == "dry_run"
    assert service.list_documents("KB1") == []
