import json
from pathlib import Path

import pytest

from app.services.traceability_gate.export_guard import (
    create_export_override,
    evaluate_export,
    guard_export,
)
from app.services.traceability_gate.traceability import build_traceability
from app.services.web_test_design_artifact_service import (
    export_incremental_testcases_excel,
    export_testcases_excel,
)


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _case(**overrides):
    item = {
        "schema_version": "2.0",
        "test_case_id": "TC-1",
        "testcase_id": "TC-1",
        "title": "Save valid record",
        "objective": "Verify record saving",
        "preconditions": ["User is signed in"],
        "test_data": [{"name": "name", "value": "Example"}],
        "steps": [{"step_number": 1, "action": "Submit the record"}],
        "expected_results": [{
            "step_number": 1,
            "expected_result": "The record is saved",
            "source_refs": [
                {"source_type": "JIRA", "source_id": "AC-1"},
                {"source_type": "KNOWLEDGE_BASE", "source_id": "KB-1"},
            ],
        }],
        "postconditions": [],
        "priority": "HIGH",
        "test_type": "FUNCTIONAL",
        "origin": "REQUIREMENT",
        "requirement_refs": ["AC-1", "BR-1"],
        "knowledge_refs": ["KB-1"],
        "coverage_refs": ["COV-1"],
        "scenario_refs": ["SC-1"],
        "assumptions": [],
        "unresolved_questions": [],
        "automation_candidate": True,
        "tags": [],
    }
    item.update(overrides)
    return item


def _workspace(tmp_path: Path, *, approved=True):
    root = tmp_path / "requirements" / "QA-10"
    _write(root / "analysis/requirement_summary.json", {
        "validations": [{"id": "AC-1", "description": "The record is saved"}],
        "business_rules": [{"id": "BR-1", "description": "Only valid records are saved"}],
    })
    _write(root / "analysis/structured_analysis.json", {
        "schema_version": "1.0", "business_rules": []
    })
    _write(root / "analysis/scenarios.json", [{
        "scenario_id": "SC-1",
        "title": "Save record",
        "coverage_ids": ["COV-1"],
    }])
    _write(root / "test-design/coverage_model.json", {
        "version": "1.0",
        "coverage_model_id": "CM-1",
        "ticket_id": "QA-10",
        "requirement_refs": ["AC-1", "BR-1"],
        "coverage_conditions": [{
            "condition_id": "COV-1",
            "condition_type": "MANDATORY",
            "title": "Save valid record",
            "mandatory": True,
            "source_refs": [{"source_type": "jira", "source_identifier": "AC-1"}],
        }],
    })
    _write(root / "knowledge/selected_references.json", [{
        "source_result_id": "KB-1",
        "classification": "ACCEPTED",
        "citation": "Business rule KB",
    }])
    _write(root / "knowledge/conflicts.json", [])
    _write(root / "test-design/test_quality_report.json", {
        "review_status": "APPROVED", "issues": []
    })
    _write(root / "testcases/testcase_session.json", {
        "current_version": "v1",
        "approved": approved,
        "approved_version": "v1" if approved else None,
    })
    _write(root / "testcases/testcases_v1.json", [_case()])
    _write(root / "testcases/testcases.json", [_case()])
    return root


def _enable_blocking(monkeypatch):
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "true")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_MODE", "block")


def test_complete_traceability_covers_full_chain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    artifact = build_traceability(
        ticket_id="QA-10",
        testcases=[_case()],
        selected_testcase_version="v1",
    )
    assert artifact.validation_issues == []
    node_ids = {item.node_id for item in artifact.nodes}
    assert all(edge.source_id in node_ids and edge.target_id in node_ids for edge in artifact.edges)
    assert {
        "JIRA_SOURCE_SECTION", "ACCEPTANCE_CRITERION", "BUSINESS_RULE",
        "KNOWLEDGE_REFERENCE", "COVERAGE_CONDITION", "SCENARIO",
        "TEST_CASE", "EXPECTED_RESULT",
    } <= {item.node_type.value for item in artifact.nodes}
    assert (tmp_path / "requirements/QA-10/traceability.json").exists()


def test_uncovered_acceptance_criterion_blocks_when_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    _enable_blocking(monkeypatch)
    case = _case(requirement_refs=["BR-1"])
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[case], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "BLOCKED"
    assert "AC-1" in decision.uncovered_requirements


def test_unsupported_expected_result_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    _enable_blocking(monkeypatch)
    case = _case()
    case["expected_results"][0]["source_refs"] = []
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[case], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "BLOCKED"
    assert decision.unsupported_results


def test_unapproved_knowledge_reference_is_not_added_as_edge_and_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    _enable_blocking(monkeypatch)
    case = _case(knowledge_refs=["KB-NOT-APPROVED"])
    case["expected_results"][0]["source_refs"] = [
        {"source_type": "KNOWLEDGE_BASE", "source_id": "KB-NOT-APPROVED"}
    ]
    artifact = build_traceability(
        ticket_id="QA-10", testcases=[case], selected_testcase_version="v1"
    )
    assert any(item.category == "UNAPPROVED_KNOWLEDGE_REFERENCE" for item in artifact.validation_issues)
    assert not any("KB-NOT-APPROVED" in edge.source_id for edge in artifact.edges)
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[case], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "BLOCKED"


def test_unresolved_conflict_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _workspace(tmp_path)
    _enable_blocking(monkeypatch)
    _write(root / "knowledge/conflicts.json", [{
        "conflict_id": "CF-1", "status": "OPEN", "human_confirmation_required": True
    }])
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "BLOCKED"
    assert decision.conflicts == ["CF-1"]


def test_missing_qa_approval_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    _enable_blocking(monkeypatch)
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "BLOCKED"
    assert any(item.category == "MISSING_QA_APPROVAL" for item in decision.blockers)


def test_quality_blocker_respects_individual_blocking_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _workspace(tmp_path)
    _enable_blocking(monkeypatch)
    _write(root / "test-design/test_quality_report.json", {
        "review_status": "NEEDS_QA_REVIEW",
        "issues": [{
            "issue_id": "QUALITY-1",
            "severity": "BLOCKER",
            "category": "OUT_OF_SCOPE_CASE",
            "explanation": "Case is out of scope",
        }],
    })
    assert evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    ).status.value == "BLOCKED"
    monkeypatch.setenv("EXPORT_GATE_BLOCK_UNRESOLVED_BLOCKERS", "false")
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    assert decision.status.value == "ALLOWED_WITH_WARNINGS"
    assert any(item.blocker_id == "QUALITY-1" for item in decision.warnings)


def test_authorized_override_is_append_only_and_allows_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    _enable_blocking(monkeypatch)
    monkeypatch.setenv("EXPORT_GATE_QA_LEAD_IDS", "qa.lead")
    decision = evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    )
    override = create_export_override(
        ticket_id="QA-10",
        testcases=[_case()],
        testcase_version="v1",
        export_format="function_based_xlsx",
        reason="Approved for a controlled release",
        user_identity="qa.lead",
        affected_blocker_ids=[item.blocker_id for item in decision.blockers],
        scope="function_based_xlsx:v1",
    )
    assert override["user_identity"] == "qa.lead"
    assert evaluate_export(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx",
    ).status.value == "OVERRIDDEN"
    audit_lines = (tmp_path / "requirements/QA-10/audit/export_overrides.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["reason"] == "Approved for a controlled release"


def test_unauthorized_and_anonymous_override_are_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    _enable_blocking(monkeypatch)
    monkeypatch.setenv("EXPORT_GATE_QA_LEAD_IDS", "qa.lead")
    kwargs = dict(
        ticket_id="QA-10", testcases=[_case()], testcase_version="v1",
        export_format="function_based_xlsx", reason="reason",
        affected_blocker_ids=["anything"], scope="function_based_xlsx:v1",
    )
    with pytest.raises(PermissionError, match="Anonymous"):
        create_export_override(user_identity="", **kwargs)
    with pytest.raises(PermissionError, match="not authorized"):
        create_export_override(user_identity="qa.user", **kwargs)


def test_feature_disabled_restores_existing_behavior_and_writes_no_trace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "false")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "false")
    decision = guard_export(
        ticket_id="QA-10", testcases=[{"title": "invalid legacy case"}],
        testcase_version="v1", export_format="function_based_xlsx",
    )
    assert decision.status.value == "ALLOWED"
    assert not (tmp_path / "requirements/QA-10/traceability.json").exists()


def test_report_only_traceability_warns_but_does_not_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "true")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "false")
    decision = guard_export(
        ticket_id="QA-10", testcases=[{"testcase_id": "TC-LEGACY", "expected_results": ["Done"]}],
        testcase_version="v1", export_format="function_based_xlsx",
    )
    assert decision.status.value == "ALLOWED_WITH_WARNINGS"
    assert (tmp_path / "requirements/QA-10/traceability.json").exists()


def test_warning_only_export_guard_reports_without_blocking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path, approved=False)
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "true")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_MODE", "warn")
    decision = guard_export(
        ticket_id="QA-10", testcases=[{"testcase_id": "TC-LEGACY", "expected_results": ["Done"]}],
        testcase_version="v1", export_format="function_based_xlsx",
    )
    assert decision.status.value == "ALLOWED_WITH_WARNINGS"
    assert decision.blockers == []
    assert decision.warnings


def test_existing_full_exporter_receives_unchanged_selected_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "false")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "false")
    selected = [{"testcase_id": "TC-EXACT", "title": "Exact input"}]
    captured = {}
    monkeypatch.setattr(
        "app.services.web_test_design_artifact_service.get_testcases",
        lambda ticket_id, version: selected,
    )
    monkeypatch.setattr(
        "app.services.web_test_design_artifact_service.export_function_based_testcases_to_excel",
        lambda **kwargs: captured.update(kwargs) or "full.xlsx",
    )
    assert export_testcases_excel("QA-10", "v1") == Path("full.xlsx")
    assert captured["testcases"] is selected


def test_existing_incremental_exporter_receives_unchanged_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _workspace(tmp_path)
    monkeypatch.setenv("TRACEABILITY_GATE_ENABLED", "false")
    monkeypatch.setenv("EXPORT_QUALITY_GATE_ENABLED", "false")
    incremental = [{"testcase_id": "TC-INC", "title": "Incremental input"}]
    _write(root / "generated/latest_testcases.json", incremental)
    captured = {}
    monkeypatch.setattr(
        "app.services.web_test_design_artifact_service.export_incremental_testcases_to_excel",
        lambda **kwargs: captured.update(kwargs) or "incremental.xlsx",
    )
    assert export_incremental_testcases_excel("QA-10") == Path("incremental.xlsx")
    assert captured["testcases"] == incremental
