from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from app.config.env_loader import load_project_env

load_project_env()

from evaluation.reports.writer import default_output_dir, write_report
from evaluation.runners.workflow_runner import RunnerConfig, WorkflowEvaluationRunner
from evaluation.runners.deterministic_runner import DeterministicEvaluationRunner
from evaluation.schemas.golden_dataset import load_dataset
from evaluation.golden import resolve_dataset_file
from evaluation.compare import compare_reports


def _dataset_file(dataset_name: str) -> Path:
    return resolve_dataset_file(dataset_name)


def live_model_credentials_available() -> bool:
    return any(
        os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "COPILOT_API_KEY", "LOCAL_BASE_URL")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run workflow evaluation dataset")
    parser.add_argument("--dataset", required=True, help="Dataset name under evaluation/datasets")
    parser.add_argument("--ticket", default=None, help="Optional ticket_id filter")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory (default: reports/evaluation/<timestamp>)",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep temporary requirement workspace folders for inspection",
    )
    parser.add_argument("--deterministic", action="store_true", help="Use checked-in fixtures only; never call an LLM")
    parser.add_argument("--skip-live-without-credentials", action="store_true", help="Return success without a live run when no provider is configured")
    parser.add_argument(
        "--compare-baseline",
        nargs="?",
        const="__dataset_default__",
        default=None,
        help="Compare with a report path, or omit the path to use evaluation/baselines/<dataset>.json",
    )
    parser.add_argument("--comparison-type", choices=["baseline", "prompt", "model", "retrieval", "ranking"], default="baseline")
    parser.add_argument("--thresholds", default=None, help="JSON file mapping metrics to allowed regression")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--domain", default=None, help="Optional golden ticket domain filter")
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--retrieval-version", default=None)
    parser.add_argument("--ranking-version", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.deterministic and args.skip_live_without_credentials and not live_model_credentials_available():
        print("Live evaluation skipped: no model provider credentials/configuration available.")
        return 0

    dataset_path = _dataset_file(args.dataset)
    dataset = load_dataset(dataset_path)

    run_id = datetime.now().strftime("%Y%m%d%H%M%S")

    runner = (
        DeterministicEvaluationRunner()
        if args.deterministic
        else WorkflowEvaluationRunner(RunnerConfig(keep_workspace=args.keep_workspace))
    )

    report = runner.run_dataset(
        dataset=dataset,
        run_id=run_id,
        ticket_filter=args.ticket,
        **({"domain_filter": args.domain} if args.deterministic else {}),
    )
    versions = report.setdefault("versions", {})
    for key, value in {
        "prompt_comparison_version": args.prompt_version,
        "model_comparison_version": args.model_version,
        "retrieval": args.retrieval_version,
        "ranking": args.ranking_version,
    }.items():
        if value:
            versions[key] = value
    if args.domain and not args.deterministic:
        report["tickets"] = [item for item in report.get("tickets", []) if item.get("domain") == args.domain]
        report["aggregate_metrics"] = report.get("per_domain_metrics", {}).get(args.domain, {})
    if args.compare_baseline:
        baseline_path = (
            Path("evaluation") / "baselines" / f"{args.dataset}.json"
            if args.compare_baseline == "__dataset_default__"
            else Path(args.compare_baseline)
        )
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        thresholds = (
            json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
            if args.thresholds else {}
        )
        report = compare_reports(
            baseline,
            report,
            thresholds=thresholds,
            comparison_type=args.comparison_type,
        )

    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    paths = write_report(report, output_dir)

    print(f"JSON report: {paths['json_report']}")
    print(f"Markdown summary: {paths['markdown_summary']}")

    if args.fail_on_regression and any(
        item.get("critical") for item in report.get("detected_regressions", [])
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
