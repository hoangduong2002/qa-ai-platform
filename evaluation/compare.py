from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.reports.writer import write_report


METRIC_DIRECTIONS = {
    "expected_business_rule_match_count": "higher_better",
    "critical_scenario_coverage": "higher_better",
    "critical_test_case_coverage": "higher_better",
    "acceptance_criteria_coverage": "higher_better",
    "duplicate_test_case_rate": "lower_better",
    "unsupported_value_count": "lower_better",
    "forbidden_assumption_count": "lower_better",
    "empty_required_field_count": "lower_better",
    "workflow_failure_rate": "lower_better",
    "jira_authority_violation_count": "lower_better",
    "unsupported_result_rate": "lower_better",
    "critical_condition_coverage": "higher_better",
    "exact_code_accuracy": "higher_better",
    "schema_valid_response_rate": "higher_better",
}

CRITICAL_METRICS = {
    "jira_authority_violation_count",
    "unsupported_result_rate",
    "critical_condition_coverage",
    "exact_code_accuracy",
    "schema_valid_response_rate",
}


def _load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _regression_amount(metric: str, baseline: float, candidate: float) -> float:
    direction = METRIC_DIRECTIONS.get(metric)
    if direction == "higher_better":
        return max(0.0, baseline - candidate)
    if direction == "lower_better":
        return max(0.0, candidate - baseline)
    return 0.0


def _ticket_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ticket["ticket_id"]: ticket for ticket in report.get("tickets", [])}


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
    comparison_type: str = "baseline",
) -> dict[str, Any]:
    thresholds = thresholds or {}
    regressions: list[dict[str, Any]] = []

    baseline_tickets = _ticket_map(baseline)
    candidate_tickets = _ticket_map(candidate)

    for ticket_id, baseline_ticket in baseline_tickets.items():
        candidate_ticket = candidate_tickets.get(ticket_id)
        if not candidate_ticket:
            regressions.append(
                {
                    "ticket_id": ticket_id,
                    "metric": "missing_ticket",
                    "baseline": "present",
                    "candidate": "missing",
                }
            )
            continue

        baseline_metrics = baseline_ticket.get("metrics", {})
        candidate_metrics = candidate_ticket.get("metrics", {})

        for metric, baseline_value in baseline_metrics.items():
            if metric not in METRIC_DIRECTIONS:
                continue
            if metric not in candidate_metrics:
                regressions.append({
                    "ticket_id": ticket_id,
                    "metric": metric,
                    "baseline": baseline_value,
                    "candidate": None,
                    "regression_amount": None,
                    "threshold": float(thresholds.get(metric, 0.0)),
                    "critical": metric in CRITICAL_METRICS,
                    "reason": "candidate metric is missing",
                })
                continue
            candidate_value = candidate_metrics[metric]

            amount = _regression_amount(metric, float(baseline_value), float(candidate_value))
            tolerance = float(thresholds.get(metric, 0.0))
            if amount > tolerance:
                regressions.append(
                    {
                        "ticket_id": ticket_id,
                        "metric": metric,
                        "baseline": baseline_value,
                        "candidate": candidate_value,
                        "regression_amount": amount,
                        "threshold": tolerance,
                        "critical": metric in CRITICAL_METRICS,
                    }
                )

    for metric, baseline_value in baseline.get("aggregate_metrics", {}).items():
        if metric not in METRIC_DIRECTIONS:
            continue

        candidate_aggregate = candidate.get("aggregate_metrics", {})
        if metric not in candidate_aggregate:
            regressions.append({
                "ticket_id": "__aggregate__",
                "metric": metric,
                "baseline": baseline_value,
                "candidate": None,
                "regression_amount": None,
                "threshold": float(thresholds.get(metric, 0.0)),
                "critical": metric in CRITICAL_METRICS,
                "reason": "candidate metric is missing",
            })
            continue
        candidate_value = candidate_aggregate[metric]

        amount = _regression_amount(metric, float(baseline_value), float(candidate_value))
        tolerance = float(thresholds.get(metric, 0.0))
        if amount > tolerance:
            regressions.append(
                {
                    "ticket_id": "__aggregate__",
                    "metric": metric,
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                    "regression_amount": amount,
                    "threshold": tolerance,
                    "critical": metric in CRITICAL_METRICS,
                }
            )

    compared = dict(candidate)
    compared["comparison"] = {
        "type": comparison_type,
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "compared_at": datetime.now().isoformat(),
        "thresholds": thresholds,
    }
    compared["detected_regressions"] = regressions

    return compared


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare evaluation reports")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON report")
    parser.add_argument("--candidate", required=True, help="Path to candidate JSON report")
    parser.add_argument("--output-dir", default=None, help="Optional output directory")
    parser.add_argument("--thresholds", default=None, help="JSON file mapping metric names to allowed regression")
    parser.add_argument("--comparison-type", choices=["baseline", "prompt", "model", "retrieval", "ranking"], default="baseline")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero when a critical regression exceeds its threshold")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    baseline = _load_report(Path(args.baseline))
    candidate = _load_report(Path(args.candidate))

    thresholds = _load_report(Path(args.thresholds)) if args.thresholds else {}
    compared = compare_reports(
        baseline=baseline,
        candidate=candidate,
        thresholds=thresholds,
        comparison_type=args.comparison_type,
    )

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("reports") / "evaluation" / f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    paths = write_report(compared, output_dir)

    print(f"JSON report: {paths['json_report']}")
    print(f"Markdown summary: {paths['markdown_summary']}")
    print(f"Regressions detected: {len(compared.get('detected_regressions', []))}")

    if args.fail_on_regression and any(item.get("critical") for item in compared.get("detected_regressions", [])):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
