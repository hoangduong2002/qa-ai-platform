from __future__ import annotations

from evaluation.compare import compare_reports


def test_compare_reports_detects_regression() -> None:
    baseline = {
        "run_id": "b1",
        "tickets": [
            {
                "ticket_id": "SAMPLE-001",
                "metrics": {
                    "critical_test_case_coverage": 1.0,
                    "workflow_failure_rate": 0.0,
                },
            }
        ],
        "aggregate_metrics": {
            "critical_test_case_coverage": 1.0,
            "workflow_failure_rate": 0.0,
        },
    }

    candidate = {
        "run_id": "c1",
        "tickets": [
            {
                "ticket_id": "SAMPLE-001",
                "metrics": {
                    "critical_test_case_coverage": 0.0,
                    "workflow_failure_rate": 1.0,
                },
            }
        ],
        "aggregate_metrics": {
            "critical_test_case_coverage": 0.0,
            "workflow_failure_rate": 1.0,
        },
    }

    compared = compare_reports(baseline=baseline, candidate=candidate)

    assert compared["detected_regressions"]
    assert any(
        item["metric"] == "critical_test_case_coverage"
        for item in compared["detected_regressions"]
    )
