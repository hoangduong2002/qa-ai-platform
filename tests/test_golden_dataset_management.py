from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.golden import add_reviewed_ticket, resolve_dataset_file
from evaluation.schemas.golden_dataset import load_dataset


def _seed(tmp_path: Path) -> tuple[Path, Path, dict]:
    datasets = tmp_path / "evaluation" / "datasets"
    root = datasets / "demo"
    root.mkdir(parents=True)
    source = json.loads(Path(__file__).parents[1].joinpath("evaluation/datasets/weclever_golden/dataset.json").read_text(encoding="utf-8"))
    source["dataset_id"] = "demo"
    (root / "dataset.json").write_text(json.dumps(source), encoding="utf-8")
    requirements = tmp_path / "requirements"
    session = requirements / "PROD-123" / "testcases"
    session.mkdir(parents=True)
    (session / "testcase_session.json").write_text(json.dumps({"approved": True, "approved_version": "v3"}), encoding="utf-8")
    expected = dict(source["tickets"][0])
    expected["ticket_id"] = "PROD-123"
    expected["jira_source_data"] = {"summary": "Owner qa@example.com", "api_token": "do-not-store"}
    expected["workspace_seed"] = json.loads(json.dumps(expected["workspace_seed"]).replace("SAMPLE-001", "PROD-123"))
    return datasets, requirements, expected


def test_golden_dataset_creates_approved_immutable_redacted_version(tmp_path, monkeypatch) -> None:
    datasets, requirements, expected = _seed(tmp_path)
    monkeypatch.setenv("GOLDEN_DATASET_REVIEWER_IDS", "qa.lead")
    record = add_reviewed_ticket(
        dataset_name="demo", ticket_id="PROD-123", expected_ticket=expected,
        reviewed_by="qa.lead", change_reason="Reviewed payment baseline",
        datasets_root=datasets, requirements_root=requirements,
    )
    assert record["dataset_version"] == "1.0.1"
    version_path = datasets / "demo" / record["dataset_path"]
    assert version_path.exists()
    payload_text = version_path.read_text(encoding="utf-8")
    assert "PROD-123" not in payload_text
    assert "qa@example.com" not in payload_text
    assert "do-not-store" not in payload_text
    assert load_dataset(resolve_dataset_file("demo", datasets_root=datasets)).dataset_version == "1.0.1"
    assert (datasets / "demo" / "dataset.json").read_text(encoding="utf-8").find('"1.0.0"') >= 0

    with pytest.raises(ValueError, match="expectations_changed_reason"):
        add_reviewed_ticket(
            dataset_name="demo", ticket_id="PROD-123", expected_ticket=expected,
            reviewed_by="qa.lead", change_reason="Change baseline",
            datasets_root=datasets, requirements_root=requirements,
        )
    changed = add_reviewed_ticket(
        dataset_name="demo", ticket_id="PROD-123", expected_ticket=expected,
        reviewed_by="qa.lead", change_reason="Approved correction",
        expectations_changed_reason="Expected wording was clarified by QA",
        datasets_root=datasets, requirements_root=requirements,
    )
    assert changed["dataset_version"] == "1.0.2"
    assert (datasets / "demo" / "versions" / "1.0.1" / "dataset.json").exists()
    assert (datasets / "demo" / "versions" / "1.0.2" / "dataset.json").exists()


def test_golden_dataset_requires_approval_and_authorization(tmp_path, monkeypatch) -> None:
    datasets, requirements, expected = _seed(tmp_path)
    monkeypatch.setenv("GOLDEN_DATASET_REVIEWER_IDS", "qa.lead")
    with pytest.raises(PermissionError):
        add_reviewed_ticket(
            dataset_name="demo", ticket_id="PROD-123", expected_ticket=expected,
            reviewed_by="unknown", change_reason="Attempt",
            datasets_root=datasets, requirements_root=requirements,
        )
    (requirements / "PROD-123" / "testcases" / "testcase_session.json").write_text(json.dumps({"approved": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="approved"):
        add_reviewed_ticket(
            dataset_name="demo", ticket_id="PROD-123", expected_ticket=expected,
            reviewed_by="qa.lead", change_reason="Attempt",
            datasets_root=datasets, requirements_root=requirements,
        )
