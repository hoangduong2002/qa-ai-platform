import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.test_case_generator_v2.inputs import build_generator_v2_inputs
from app.services.test_case_generator_v2.models import TestCaseSetV2 as CaseSetV2
from app.services.test_case_generator_v2.service import (
    TestCaseGeneratorV2ValidationError as GeneratorV2ValidationError,
    _validate_traceability,
    run_generator_rollout,
    select_generator_output,
)
from app.services.web_test_design_artifact_service import get_testcases


def _inputs(*, coverage_ids=("COV-1",)):
    return {
        "ticket_id": "QA-8",
        "authoritative_jira_source": "The user can save a valid record.",
        "approved_analysis": {},
        "accepted_knowledge_references": [],
        "unresolved_conflicts": [],
        "coverage_model": {
            "requirement_refs": ["QA-8"],
            "coverage_conditions": [
                {
                    "condition_id": condition_id,
                    "mandatory": True,
                    "risk_priority": "HIGH",
                }
                for condition_id in coverage_ids
            ],
        },
        "scenarios": [{"scenario_id": "SC-1", "coverage_ids": list(coverage_ids)}],
        "test_scope_constraints": {},
        "output_format_constraints": {},
    }


def _case(**overrides):
    payload = {
        "schema_version": "2.0",
        "test_case_id": "TCV2-001",
        "title": "Save a valid record",
        "objective": "Verify that a valid record is saved",
        "preconditions": ["The user is signed in"],
        "test_data": [
            {
                "name": "record name",
                "value": "Example",
                "source_refs": [{"source_type": "JIRA", "source_id": "QA-8"}],
            }
        ],
        "steps": [{"step_number": 1, "action": "Submit the valid record"}],
        "expected_results": [
            {
                "step_number": 1,
                "expected_result": "The record is saved",
                "source_refs": [{"source_type": "JIRA", "source_id": "QA-8"}],
            }
        ],
        "postconditions": ["The record exists"],
        "priority": "HIGH",
        "test_type": "FUNCTIONAL",
        "origin": "REQUIREMENT",
        "requirement_refs": ["QA-8"],
        "knowledge_refs": [],
        "coverage_refs": ["COV-1"],
        "scenario_refs": ["SC-1"],
        "assumptions": [],
        "unresolved_questions": [],
        "automation_candidate": True,
        "tags": ["save"],
    }
    payload.update(overrides)
    return payload


def _case_set(*cases):
    return CaseSetV2.model_validate(
        {
            "schema_version": "2.0",
            "generator_version": "v2",
            "ticket_id": "QA-8",
            "test_cases": list(cases or (_case(),)),
        }
    )


def test_schema_valid_case_has_source_traceability():
    result = _case_set()
    _validate_traceability(result, _inputs())
    assert result.test_cases[0].expected_results[0].source_refs[0].source_id == "QA-8"


def test_unsupported_expected_result_is_rejected():
    case = _case()
    case["expected_results"][0]["source_refs"] = []
    with pytest.raises(ValidationError, match="authoritative/approved source"):
        _case_set(case)


def test_unsupported_expected_result_can_be_explicit_unresolved_question():
    question = "Should the record remain visible after submission?"
    case = _case(unresolved_questions=[question])
    case["expected_results"][0] = {
        "step_number": 1,
        "expected_result": "The record remains visible",
        "source_refs": [],
        "unresolved_question": question,
    }
    result = _case_set(case)
    assert result.test_cases[0].unresolved_questions == [question]


def test_every_selected_coverage_condition_must_be_mapped():
    with pytest.raises(GeneratorV2ValidationError, match="COV-2"):
        _validate_traceability(_case_set(), _inputs(coverage_ids=("COV-1", "COV-2")))


def test_duplicate_cases_are_rejected():
    duplicate = _case(test_case_id="TCV2-002")
    with pytest.raises(ValidationError, match="duplicate or near-duplicate"):
        _case_set(_case(), duplicate)


def test_historical_defect_cannot_define_expected_behavior():
    case = _case(origin="HISTORICAL_DEFECT")
    historical = {
        "source_type": "HISTORICAL_DEFECT",
        "source_id": "DEFECT-7",
        "classification": "ACCEPTED",
    }
    case["expected_results"][0]["source_refs"] = [historical]
    with pytest.raises(ValidationError, match="authoritative/approved source"):
        _case_set(case)


def test_input_filters_unreviewed_references_and_resolved_conflicts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {
        "ticket_id": "QA-8",
        "requirement_context": "Jira source",
        "structured_analysis": {"functional_requirements": []},
        "selected_references": [
            {"result_id": "KB-1", "classification": "ACCEPTED"},
            {"result_id": "KB-2", "classification": "REJECTED"},
            {"result_id": "KB-3", "classification": "NEEDS_CONFIRMATION"},
        ],
        "knowledge_conflicts": [
            {"conflict_id": "OPEN-1", "status": "OPEN"},
            {"conflict_id": "DONE-1", "status": "RESOLVED"},
        ],
        "scenarios": [],
        "test_scope": {},
    }
    inputs = build_generator_v2_inputs(state)
    assert [item["result_id"] for item in inputs["accepted_knowledge_references"]] == ["KB-1"]
    assert [item["conflict_id"] for item in inputs["unresolved_conflicts"]] == ["OPEN-1"]


def test_shadow_failure_is_isolated_from_v1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_CASE_GENERATOR_VERSION", "v2-shadow")
    monkeypatch.setattr(
        "app.services.test_case_generator_v2.service.generate_testcases_v2",
        lambda state: (_ for _ in ()).throw(RuntimeError("shadow failed")),
    )
    v1 = [{"testcase_id": "TC001", "title": "Legacy"}]
    result = run_generator_rollout({"ticket_id": "QA-8"}, v1)
    assert result["production_testcases"] == v1
    assert result["test_case_generator_run"]["production_generator"] == "v1"
    assert (tmp_path / "requirements/QA-8/test-design/testcases_v2_error.json").exists()


def test_shadow_success_writes_comparison_and_keeps_v1_production(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_CASE_GENERATOR_VERSION", "v2-shadow")
    monkeypatch.setattr(
        "app.services.test_case_generator_v2.service.generate_testcases_v2",
        lambda state: (_case_set(), _inputs()),
    )
    v1 = [{"testcase_id": "TC001", "title": "Legacy"}]
    result = run_generator_rollout({"ticket_id": "QA-8"}, v1)
    design_dir = tmp_path / "requirements/QA-8/test-design"
    assert result["production_testcases"] == v1
    assert result["test_case_generator_run"]["production_generator"] == "v1"
    assert (design_dir / "testcases_v1.json").exists()
    assert (design_dir / "testcases_v2.json").exists()
    comparison = json.loads(
        (design_dir / "generator_comparison.json").read_text(encoding="utf-8")
    )
    assert comparison["metrics"]["test_count"] == {"v1": 1, "v2": 1}
    assert comparison["metrics"]["source_reference_completeness"]["v2"] == 1.0


def test_manual_selection_can_choose_v2_and_return_to_v1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_CASE_GENERATOR_VERSION", "v2-manual")
    monkeypatch.setattr(
        "app.services.test_case_generator_v2.service.generate_testcases_v2",
        lambda state: (_case_set(), _inputs()),
    )
    v1 = [{"testcase_id": "TC001", "title": "Legacy"}]
    select_generator_output("QA-8", "v2", selected_by="qa")
    assert run_generator_rollout({"ticket_id": "QA-8"}, v1)["production_testcases"][0]["test_case_id"] == "TCV2-001"
    select_generator_output("QA-8", "v1", selected_by="qa")
    assert run_generator_rollout({"ticket_id": "QA-8"}, v1)["production_testcases"] == v1


def test_shadow_artifacts_do_not_change_legacy_export_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    legacy_dir = tmp_path / "requirements/QA-8/testcases"
    design_dir = tmp_path / "requirements/QA-8/test-design"
    legacy_dir.mkdir(parents=True)
    design_dir.mkdir(parents=True)
    legacy = [{"testcase_id": "TC001", "title": "Legacy"}]
    (legacy_dir / "testcases.json").write_text(json.dumps(legacy), encoding="utf-8")
    (design_dir / "testcases_v2.json").write_text(
        json.dumps(_case_set().model_dump(mode="json")), encoding="utf-8"
    )
    loaded = get_testcases("QA-8")
    assert loaded[0]["testcase_id"] == "TC001"
    assert loaded[0]["title"] == "Legacy"
    assert "test_case_id" not in loaded[0]


def test_v1_mode_is_immediate_feature_rollback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_CASE_GENERATOR_VERSION", "v1")
    v1 = [{"testcase_id": "TC001", "title": "Legacy"}]
    result = run_generator_rollout({"ticket_id": "QA-8"}, v1)
    assert result["production_testcases"] == v1
    assert not (tmp_path / "requirements/QA-8/test-design").exists()
