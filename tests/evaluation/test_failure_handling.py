from __future__ import annotations

from pathlib import Path

from evaluation.runners.workflow_runner import WorkflowEvaluationRunner
from evaluation.schemas.golden_dataset import GoldenTicket


def _ticket_fixture() -> GoldenTicket:
    return GoldenTicket.model_validate(
        {
            "ticket_id": "SAMPLE-001",
            "jira_source_data": {"summary": "x"},
            "expected_business_rules": [],
            "expected_ambiguities": [],
            "expected_missing_information": [],
            "expected_contradictions": [],
            "critical_scenarios": [],
            "critical_test_cases": [],
            "forbidden_assumptions": [],
            "expected_acceptance_criteria_coverage": {
                "required_items": [],
                "minimum_coverage_ratio": 0.0,
            },
            "evaluation_notes": "",
            "dataset_version": "1.0.0",
            "workspace_seed": {
                "ticket": {},
                "source": {
                    "description": "d",
                    "comments": "c",
                },
                "approved_test_case_structure": {
                    "main_functions": []
                },
            },
        }
    )


def test_runner_captures_workflow_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    runner = WorkflowEvaluationRunner()

    def _raise_error(state):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(
        "evaluation.runners.workflow_runner.requirement_summary_graph.invoke",
        _raise_error,
    )

    result = runner.run_ticket(_ticket_fixture(), run_id="RUN1")

    assert result["success"] is False
    assert "forced failure" in (result.get("error") or "")
    assert result["metrics"]["workflow_failure_rate"] == 1.0
