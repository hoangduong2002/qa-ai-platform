import json

import pytest

from app.services.test_case_generator_v2.models import TestCaseSetV2 as CaseSetV2
from app.services.test_case_generator_v2.service import run_generator_rollout
from app.services.test_quality_review.deterministic import run_deterministic_checks
from app.services.test_quality_review.models import (
    CorrectionChange,
    CorrectionResult,
    ReviewStatus,
    TestQualityReportV1 as QualityReport,
)
from app.services.test_quality_review.service import (
    assert_test_quality_export_allowed,
    run_test_quality_pipeline,
)


def _inputs(*, excluded=None, acceptance=False, coverage_ids=("COV-1",)):
    analysis = {
        "validations": [
            {"id": "AC-1", "description": "The record is saved"}
        ] if acceptance else []
    }
    return {
        "ticket_id": "QA-9",
        "authoritative_jira_source": "A valid record is saved for ticket QA-9.",
        "approved_analysis": analysis,
        "accepted_knowledge_references": [],
        "confirmed_clarifications": {},
        "unresolved_conflicts": [],
        "coverage_model": {
            "requirement_refs": ["QA-9", *( ["AC-1"] if acceptance else [])],
            "coverage_conditions": [
                {
                    "condition_id": item,
                    "condition_type": "MANDATORY",
                    "mandatory": True,
                    "source_refs": [],
                }
                for item in coverage_ids
            ],
            "out_of_scope_combinations": [],
        },
        "scenarios": [{"scenario_id": "SC-1"}],
        "test_scope_constraints": {"excluded_categories": excluded or []},
        "output_format_constraints": {},
    }


def _case(**overrides):
    payload = {
        "schema_version": "2.0",
        "test_case_id": "TCV2-001",
        "title": "Save a valid record",
        "objective": "Verify that a valid record is saved",
        "preconditions": ["The user is signed in"],
        "test_data": [{
            "name": "record name",
            "value": "Example",
            "source_refs": [{"source_type": "JIRA", "source_id": "QA-9"}],
        }],
        "steps": [{"step_number": 1, "action": "Submit the valid record"}],
        "expected_results": [{
            "step_number": 1,
            "expected_result": "The record is saved",
            "source_refs": [{"source_type": "JIRA", "source_id": "QA-9"}],
        }],
        "postconditions": ["The record exists"],
        "priority": "HIGH",
        "test_type": "FUNCTIONAL",
        "origin": "REQUIREMENT",
        "requirement_refs": ["QA-9"],
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


def _case_set(case=None):
    return CaseSetV2.model_validate({
        "schema_version": "2.0",
        "generator_version": "v2",
        "ticket_id": "QA-9",
        "test_cases": [case or _case()],
    })


def _empty_llm_report(ticket_id="QA-9"):
    return QualityReport(
        ticket_id=ticket_id,
        review_status="APPROVED",
        summary="No additional LLM findings.",
    )


def _categories(payload, inputs):
    issues, _, _ = run_deterministic_checks(payload, inputs)
    return {item.category.value for item in issues}


def test_detects_unsupported_amount_even_with_generic_jira_reference():
    case = _case()
    case["expected_results"][0]["expected_result"] = "The account is charged $100"
    assert "INVENTED_AMOUNT" in _categories([case], _inputs())


def test_reviewer_cannot_approve_unsupported_expected_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    case = _case()
    case["expected_results"][0]["expected_result"] = "The account is charged $100"
    monkeypatch.setattr(
        "app.services.test_quality_review.service.call_reviewer_llm",
        lambda **kwargs: (
            _empty_llm_report(),
            {"profile": "independent-reviewer"},
        ),
    )
    result = run_test_quality_pipeline(
        state={}, inputs=_inputs(), testcases=_case_set(case)
    )
    assert result["test_quality_report"]["review_status"] == "NEEDS_QA_REVIEW"
    assert any(
        item["category"] == "INVENTED_AMOUNT"
        for item in result["test_quality_report"]["issues"]
    )


def test_detects_missing_acceptance_criterion_coverage():
    assert "UNCOVERED_ACCEPTANCE_CRITERION" in _categories([_case()], _inputs(acceptance=True))


def test_detects_duplicate_cases_and_ids_on_raw_payload():
    duplicate = _case()
    categories = _categories([_case(), duplicate], _inputs())
    assert "DUPLICATE_ID" in categories
    assert "DUPLICATE_CONTENT" in categories


def test_detects_out_of_scope_case():
    case = _case(title="Admin workflow is excluded")
    assert "OUT_OF_SCOPE_CASE" in _categories([case], _inputs(excluded=["admin workflow"]))


def test_detects_missing_reference_and_deterministic_required_fields():
    raw = _case()
    raw["test_case_id"] = ""
    raw["title"] = ""
    raw["steps"] = []
    raw["expected_results"] = [{"step_number": 1, "expected_result": "Saved", "source_refs": []}]
    raw["requirement_refs"] = []
    raw["coverage_refs"] = []
    raw["scenario_refs"] = []
    categories = _categories([raw], _inputs())
    assert {"MISSING_ID", "MISSING_TITLE", "EMPTY_STEPS", "MISSING_SOURCE_REFERENCE", "MISSING_TRACEABILITY"} <= categories


def test_correction_success_is_re_reviewed_and_approved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    calls = {"review": 0, "correct": 0}
    inputs = _inputs(excluded=["admin workflow"])
    original = _case_set(_case(title="Admin workflow is excluded"))
    corrected_case = _case(title="Save a valid record")
    corrected = _case_set(corrected_case)

    def reviewer(**kwargs):
        calls["review"] += 1
        return _empty_llm_report(), {"profile": "independent-reviewer", "model": "review-model"}

    def corrector(**kwargs):
        calls["correct"] += 1
        return CorrectionResult(
            corrected_testcases=corrected,
            changes=[CorrectionChange(
                test_case_id="TCV2-001",
                issue_ids=[item.issue_id for item in kwargs["issues"]],
                fields_changed=["title"],
                description="Removed the out-of-scope title.",
            )],
        ), {"profile": "constrained-corrector", "model": "correct-model"}

    monkeypatch.setattr("app.services.test_quality_review.service.call_reviewer_llm", reviewer)
    monkeypatch.setattr("app.services.test_quality_review.service.call_corrector_llm", corrector)
    result = run_test_quality_pipeline(state={}, inputs=inputs, testcases=original)
    assert calls == {"review": 2, "correct": 1}
    assert result["test_quality_report"]["review_status"] == ReviewStatus.APPROVED.value
    assert result["correction_history"]["correction_attempts"][0]["status"] == "succeeded"
    assert (tmp_path / "requirements/QA-9/test-design/testcases_v2_reviewed.json").exists()


def test_correction_failure_remains_needs_qa_review_and_loop_is_bounded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    calls = {"review": 0, "correct": 0}
    inputs = _inputs(excluded=["admin workflow"])
    original = _case_set(_case(title="Admin workflow is excluded"))

    def reviewer(**kwargs):
        calls["review"] += 1
        return _empty_llm_report(), {"profile": "independent-reviewer"}

    def corrector(**kwargs):
        calls["correct"] += 1
        raise RuntimeError("correction unavailable")

    monkeypatch.setattr("app.services.test_quality_review.service.call_reviewer_llm", reviewer)
    monkeypatch.setattr("app.services.test_quality_review.service.call_corrector_llm", corrector)
    result = run_test_quality_pipeline(state={}, inputs=inputs, testcases=original)
    assert calls == {"review": 2, "correct": 1}
    assert result["test_quality_report"]["review_status"] == "NEEDS_QA_REVIEW"
    assert result["correction_history"]["correction_attempts"][0]["status"] == "failed"


def test_warn_mode_never_blocks_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    report_path = tmp_path / "requirements/QA-9/test-design/test_quality_report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"review_status": "NEEDS_QA_REVIEW"}), encoding="utf-8")
    assert_test_quality_export_allowed("QA-9")


def test_warn_review_in_shadow_keeps_v1_as_production(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_CASE_GENERATOR_VERSION", "v2-shadow")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    monkeypatch.setattr(
        "app.services.test_case_generator_v2.service.generate_testcases_v2",
        lambda state: (_case_set(), _inputs()),
    )
    monkeypatch.setattr(
        "app.services.test_quality_review.service.call_reviewer_llm",
        lambda **kwargs: (
            _empty_llm_report(),
            {"profile": "independent-reviewer"},
        ),
    )
    v1 = [{"testcase_id": "TC001", "title": "Legacy production case"}]
    result = run_generator_rollout({"ticket_id": "QA-9"}, v1)
    assert result["production_testcases"] == v1
    assert result["test_case_generator_run"]["production_generator"] == "v1"
    assert (tmp_path / "requirements/QA-9/test-design/test_quality_report.json").exists()


def test_block_export_mode_blocks_remaining_blockers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "block_export")
    report_path = tmp_path / "requirements/QA-9/test-design/test_quality_report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"review_status": "NEEDS_QA_REVIEW"}), encoding="utf-8")
    with pytest.raises(ValueError, match="export is blocked"):
        assert_test_quality_export_allowed("QA-9")


def test_disabled_mode_skips_reviewer_and_writes_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "false")
    monkeypatch.setattr(
        "app.services.test_quality_review.service.call_reviewer_llm",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    original = _case_set()
    result = run_test_quality_pipeline(state={}, inputs=_inputs(), testcases=original)
    assert result["reviewed_testcases"] == original
    assert result["test_quality_review_run"]["status"] == "skipped"
    assert not (tmp_path / "requirements").exists()


def test_reviewer_failure_falls_back_to_deterministic_needs_qa_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_QUALITY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TEST_QUALITY_REVIEW_MODE", "warn")
    monkeypatch.setattr(
        "app.services.test_quality_review.service.call_reviewer_llm",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("reviewer unavailable")),
    )
    result = run_test_quality_pipeline(state={}, inputs=_inputs(), testcases=_case_set())
    categories = {item["category"] for item in result["test_quality_report"]["issues"]}
    assert result["test_quality_report"]["review_status"] == "NEEDS_QA_REVIEW"
    assert "REVIEWER_FAILURE" in categories
    assert result["test_quality_review_run"]["review_attempts"] == 1
