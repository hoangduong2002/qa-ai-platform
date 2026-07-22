from __future__ import annotations

from pathlib import Path

from evaluation.compare import compare_reports
from evaluation.run import live_model_credentials_available
from evaluation.runners.deterministic_runner import DeterministicEvaluationRunner
from evaluation.schemas.golden_dataset import load_dataset


def test_regression_threshold_and_critical_failure_classification() -> None:
    baseline = {"run_id": "b", "tickets": [], "aggregate_metrics": {"critical_condition_coverage": 1.0}}
    candidate = {"run_id": "c", "tickets": [], "aggregate_metrics": {"critical_condition_coverage": 0.96}}
    tolerated = compare_reports(baseline, candidate, thresholds={"critical_condition_coverage": 0.05})
    failed = compare_reports(baseline, candidate, thresholds={"critical_condition_coverage": 0.01}, comparison_type="prompt")
    assert tolerated["detected_regressions"] == []
    assert failed["detected_regressions"][0]["critical"] is True
    assert failed["comparison"]["type"] == "prompt"


def test_deterministic_runner_is_reproducible_and_versioned() -> None:
    dataset = load_dataset(Path("evaluation/datasets/weclever_golden/dataset.json"))
    first = DeterministicEvaluationRunner().run_dataset(dataset, "run-1")
    second = DeterministicEvaluationRunner().run_dataset(dataset, "run-2")
    assert first["execution_mode"] == "deterministic"
    assert first["aggregate_metrics"] == second["aggregate_metrics"]
    assert first["versions"]["dataset"] == dataset.dataset_version
    assert "prompt_versions" in first["versions"]
    assert first["per_domain_metrics"]


def test_missing_model_credentials_can_be_detected(monkeypatch) -> None:
    for name in ("DEEPSEEK_API_KEY", "COPILOT_API_KEY", "LOCAL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert live_model_credentials_available() is False
