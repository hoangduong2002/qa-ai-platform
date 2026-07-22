from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config.env_loader import load_project_env

load_project_env()

from app.services.quality_feedback.models import FeedbackEvent
from app.services.quality_feedback.service import aggregate_feedback
from knowledge.storage.utils import atomic_write_json


EVALUATION_METRIC_MAP = {
    ("requirement_analysis", "structured_analysis_acceptance"): "schema_valid_response_rate",
    ("requirement_analysis", "missing_information_recall"): "missing_information_recall",
    ("requirement_analysis", "ambiguity_precision"): "ambiguity_precision",
    ("requirement_analysis", "unsupported_assumption_rate"): "unsupported_assumption_rate",
    ("requirement_analysis", "contradiction_detection_rate"): "contradiction_detection_rate",
    ("retrieval", "precision_at_5"): "precision_at_5",
    ("retrieval", "recall_at_10"): "recall_at_10",
    ("retrieval", "exact_code_accuracy"): "exact_code_accuracy",
    ("test_design", "acceptance_criteria_coverage"): "acceptance_criteria_coverage",
    ("test_design", "critical_condition_coverage"): "critical_condition_coverage",
    ("test_design", "duplicate_rate"): "duplicate_test_case_rate",
    ("test_design", "unsupported_result_rate"): "unsupported_result_rate",
}


def collect_feedback(requirements_root: Path = Path("requirements")) -> list[FeedbackEvent]:
    events: list[FeedbackEvent] = []
    if not requirements_root.exists():
        return events
    for path in requirements_root.glob("*/feedback/testcase_feedback.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(FeedbackEvent.model_validate_json(line))
    return events


def build_continuous_quality_report(
    events: list[FeedbackEvent],
    evaluation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    feedback = aggregate_feedback(events).model_dump(mode="json")
    metrics = feedback["metrics"]
    evaluation_report = evaluation_report or {}
    aggregate = evaluation_report.get("aggregate_metrics", {})
    for (category, output_name), input_name in EVALUATION_METRIC_MAP.items():
        if input_name in aggregate:
            metrics[category][output_name] = aggregate[input_name]
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "metrics": metrics,
        "feedback_counts": {
            "event_count": feedback["event_count"],
            "actions": feedback["action_counts"],
            "reasons": feedback["reason_counts"],
            "domains": feedback["domain_breakdown"],
        },
        "versions": {
            "evaluation": evaluation_report.get("versions", {}),
            "feedback": feedback["version_breakdown"],
            "feedback_model_identifiers": feedback["model_identifiers"],
            "feedback_model_configurations": feedback["model_configurations"],
        },
        "dataset_id": evaluation_report.get("dataset_id"),
        "dataset_version": evaluation_report.get("dataset_version"),
        "methodology_note": "Metrics show association with QA decisions; they do not establish defect-leakage causation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe continuous quality report")
    parser.add_argument("--evaluation-report", default=None)
    parser.add_argument("--requirements-root", default="requirements")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evaluation = (
        json.loads(Path(args.evaluation_report).read_text(encoding="utf-8"))
        if args.evaluation_report else {}
    )
    report = build_continuous_quality_report(
        collect_feedback(Path(args.requirements_root)), evaluation
    )
    atomic_write_json(Path(args.output), report)
    print(f"Continuous quality report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
