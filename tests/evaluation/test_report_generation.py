from __future__ import annotations

import json

from evaluation.reports.writer import write_report


def test_write_report_creates_json_and_markdown(tmp_path) -> None:
    report = {
        "run_id": "r1",
        "dataset_id": "weclever_golden",
        "dataset_version": "1.0.0",
        "generated_at": "2026-01-01T00:00:00",
        "tickets": [
            {
                "ticket_id": "SAMPLE-001",
                "success": True,
                "metrics": {"workflow_failure_rate": 0.0},
            }
        ],
        "aggregate_metrics": {"workflow_failure_rate": 0.0},
        "detected_regressions": [],
    }

    paths = write_report(report, tmp_path)

    json_payload = json.loads((tmp_path / "evaluation_report.json").read_text(encoding="utf-8"))
    markdown_payload = (tmp_path / "evaluation_summary.md").read_text(encoding="utf-8")

    assert paths["json_report"].endswith("evaluation_report.json")
    assert paths["markdown_summary"].endswith("evaluation_summary.md")
    assert json_payload["run_id"] == "r1"
    assert "# Evaluation Summary" in markdown_payload
