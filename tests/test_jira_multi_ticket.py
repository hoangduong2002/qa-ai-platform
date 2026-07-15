import json

import pytest

from app.services import jira_requirement_service as jira_service


@pytest.mark.parametrize(
    ("raw_value", "expected_main", "expected_supporting"),
    [
        ("EVNWCL-5175", "EVNWCL-5175", []),
        (
            "EVNWCL-5175, EVNWCL-5176, EVNWCL-5177",
            "EVNWCL-5175",
            ["EVNWCL-5176", "EVNWCL-5177"],
        ),
        (
            " evnwcl-5175, evnwcl-5176 ",
            "EVNWCL-5175",
            ["EVNWCL-5176"],
        ),
        (
            "EVNWCL-5175, EVNWCL-5176, EVNWCL-5176",
            "EVNWCL-5175",
            ["EVNWCL-5176"],
        ),
    ],
)
def test_parse_jira_ticket_ids(raw_value, expected_main, expected_supporting):
    main_ticket_id, supporting_ticket_ids = jira_service.parse_jira_ticket_ids(
        raw_value
    )

    assert main_ticket_id == expected_main
    assert supporting_ticket_ids == expected_supporting


def test_parse_jira_ticket_ids_rejects_empty_input():
    with pytest.raises(ValueError, match="Please enter at least one Jira ticket ID"):
        jira_service.parse_jira_ticket_ids(" , , ")


class FakeJira:
    def __init__(self):
        self.issue_calls = []

    def issue(self, issue_key, fields):
        self.issue_calls.append(issue_key)

        if issue_key == "SUP-FAIL":
            raise RuntimeError("support unavailable")

        subtasks = [{"key": "SUB-1"}] if issue_key == "MAIN-1" else []
        return {
            "key": issue_key,
            "fields": {
                "summary": f"Summary for {issue_key}",
                "description": f"Description for {issue_key}",
                "comment": {"comments": []},
                "attachment": [],
                "subtasks": subtasks,
                "status": {"name": "Open"},
                "issuetype": {"name": "Story"},
            },
        }

    def issue_get_comments(self, issue_key):
        return {"comments": []}


def _fail_if_called(*args, **kwargs):
    raise AssertionError("Figma detection/extraction must not be called")


def test_multi_ticket_load_uses_main_workspace_and_honors_disabled_options(
    tmp_path,
    monkeypatch,
):
    jira = FakeJira()
    requirements_root = tmp_path / "requirements"
    monkeypatch.setattr(jira_service, "REQUIREMENTS_ROOT", requirements_root)
    monkeypatch.setattr(jira_service, "_get_jira_client", lambda jira_pat="": jira)
    monkeypatch.setattr(
        jira_service,
        "_download_and_extract_attachments",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(jira_service, "create_workspace_from_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(jira_service, "_build_compact_context_safely", lambda ticket_id: None)
    monkeypatch.setattr(jira_service, "extract_figma_link_records_from_sources", _fail_if_called)
    monkeypatch.setattr(jira_service, "extract_figma_references_from_texts", _fail_if_called)
    monkeypatch.setattr(jira_service, "extract_figma_context_from_jira_texts", _fail_if_called)

    ticket_id = jira_service.create_requirement_from_jira(
        "main-1, support-2, sup-fail",
        load_subtasks=False,
        load_figma=False,
        source_channel="web",
    )

    assert ticket_id == "MAIN-1"
    assert jira.issue_calls == ["MAIN-1", "SUPPORT-2", "SUP-FAIL"]
    assert not (requirements_root / "SUPPORT-2").exists()

    combined_context = (
        requirements_root / "MAIN-1" / "source" / "jira_requirement.md"
    ).read_text(encoding="utf-8")
    assert "# Main Jira Ticket: MAIN-1" in combined_context
    assert "# Supporting Jira Ticket: SUPPORT-2" in combined_context
    assert "Supporting ticket SUP-FAIL could not be loaded and was skipped." in combined_context
    assert "Sub-task loading is disabled." in combined_context

    metadata = json.loads(
        (requirements_root / "MAIN-1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["main_ticket_id"] == "MAIN-1"
    assert metadata["supporting_ticket_ids"] == ["SUPPORT-2", "SUP-FAIL"]
    assert metadata["all_ticket_ids"] == ["MAIN-1", "SUPPORT-2", "SUP-FAIL"]
    assert metadata["load_subtasks"] is False
    assert metadata["load_figma"] is False
    assert metadata["supporting_ticket_warnings"] == [
        "Supporting ticket SUP-FAIL could not be loaded and was skipped."
    ]


def test_existing_single_ticket_load_still_works(tmp_path, monkeypatch):
    jira = FakeJira()
    requirements_root = tmp_path / "requirements"
    monkeypatch.setattr(jira_service, "REQUIREMENTS_ROOT", requirements_root)
    monkeypatch.setattr(jira_service, "_get_jira_client", lambda jira_pat="": jira)
    monkeypatch.setattr(
        jira_service,
        "_download_and_extract_attachments",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(jira_service, "create_workspace_from_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(jira_service, "_build_compact_context_safely", lambda ticket_id: None)

    ticket_id = jira_service.create_requirement_from_jira(
        "main-1",
        load_subtasks=False,
        load_figma=False,
    )

    assert ticket_id == "MAIN-1"
    assert jira.issue_calls == ["MAIN-1"]
    assert (requirements_root / "MAIN-1" / "source" / "jira_requirement.md").exists()


def test_main_ticket_failure_stops_with_clear_error(tmp_path, monkeypatch):
    class FailingJira:
        def issue(self, issue_key, fields):
            raise RuntimeError("main unavailable")

    monkeypatch.setattr(jira_service, "REQUIREMENTS_ROOT", tmp_path / "requirements")
    monkeypatch.setattr(
        jira_service,
        "_get_jira_client",
        lambda jira_pat="": FailingJira(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"^Failed to load main Jira ticket MAIN-1\.$",
    ):
        jira_service.create_requirement_from_jira(
            "MAIN-1, SUPPORT-2",
            load_subtasks=False,
            load_figma=False,
        )
