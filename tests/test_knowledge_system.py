import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app.services.knowledge_system_service import load_knowledge_system


KNOWLEDGE_ENV_NAMES = [
    "KNOWLEDGE_SYSTEM_ENABLED",
    "KNOWLEDGE_SYSTEM_LINK_TARGET",
    "KNOWLEDGE_SYSTEM_CONFIG_PATH",
    "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
    "KNOWLEDGE_SYSTEM_ALLOW_HTTP",
]


@pytest.fixture(autouse=True)
def clean_knowledge_environment(monkeypatch):
    for name in KNOWLEDGE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _project(**overrides):
    project = {
        "key": "weclever",
        "name": "Weclever Business Knowledge Assistant",
        "description": "Project knowledge",
        "url": "https://chatgpt.com/g/example-assistant",
        "enabled": True,
        "tags": ["Business", "RAG"],
    }
    project.update(overrides)
    return project


def test_loads_projects_from_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "knowledge_projects.json"
    config_file.write_text(
        json.dumps([_project()]),
        encoding="utf-8",
    )
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_CONFIG_PATH", str(config_file))

    result = load_knowledge_system()

    assert result["enabled"] is True
    assert len(result["projects"]) == 1
    assert result["projects"][0]["key"] == "weclever"
    assert result["projects"][0]["link_type"] == "ChatGPT GPT"


def test_loads_projects_from_environment_fallback(monkeypatch):
    monkeypatch.setenv(
        "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        json.dumps([_project(key="fallback")]),
    )

    result = load_knowledge_system()

    assert [project["key"] for project in result["projects"]] == ["fallback"]


def test_filters_disabled_projects(monkeypatch):
    monkeypatch.setenv(
        "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        json.dumps(
            [
                _project(key="enabled"),
                _project(key="disabled", enabled=False),
            ]
        ),
    )

    result = load_knowledge_system()

    assert [project["key"] for project in result["projects"]] == ["enabled"]


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "data:text/html,unsafe",
        "file:///tmp/secret",
        "http://internal.example/knowledge",
        "",
    ],
)
def test_invalid_urls_are_not_renderable(unsafe_url, monkeypatch):
    monkeypatch.setenv(
        "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        json.dumps([_project(url=unsafe_url)]),
    )

    result = load_knowledge_system()

    assert result["projects"] == []
    assert any("invalid URL" in warning for warning in result["warnings"])


def test_http_url_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_ALLOW_HTTP", "true")
    monkeypatch.setenv(
        "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        json.dumps([_project(url="http://internal.example/knowledge")]),
    )

    result = load_knowledge_system()

    assert result["projects"][0]["url"] == "http://internal.example/knowledge"


def test_missing_config_returns_empty_state_without_crashing(tmp_path, monkeypatch):
    missing_file = tmp_path / "missing.json"
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_CONFIG_PATH", str(missing_file))

    result = load_knowledge_system()

    assert result["enabled"] is True
    assert result["projects"] == []
    assert any("was not found" in warning for warning in result["warnings"])


def test_disabled_knowledge_system_returns_disabled_state(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_PROJECTS_JSON", json.dumps([_project()]))

    result = load_knowledge_system()

    assert result["enabled"] is False
    assert result["projects"] == []


def test_knowledge_route_renders_safe_external_link(monkeypatch):
    monkeypatch.setenv(
        "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        json.dumps([_project()]),
    )
    monkeypatch.setenv("KNOWLEDGE_SYSTEM_LINK_TARGET", "_blank")
    client = TestClient(app)

    response = client.get("/portal/knowledge")

    assert response.status_code == 200
    assert "Knowledge System" in response.text
    assert "Project key: weclever" in response.text
    assert "Weclever Business Knowledge Assistant" in response.text
    assert "Project knowledge" not in response.text
    assert "company ChatGPT account" not in response.text
    assert 'target="_blank"' in response.text
    assert 'rel="noopener noreferrer"' in response.text
    assert 'class="knowledge-card"' in response.text
    assert 'aria-label="Open knowledge system for project weclever"' in response.text
    assert ">\n                                Open\n" not in response.text
