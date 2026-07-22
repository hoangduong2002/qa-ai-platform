from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.schemas.golden_dataset import DatasetValidationError, load_dataset


def test_load_valid_dataset_fixture() -> None:
    dataset = load_dataset(
        Path("evaluation/datasets/weclever_golden/dataset.json")
    )

    assert dataset.dataset_id == "weclever_golden"
    assert dataset.dataset_version == "1.0.0"
    assert len(dataset.tickets) >= 1


def test_dataset_validation_rejects_missing_required_fields(tmp_path: Path) -> None:
    dataset_file = tmp_path / "dataset.json"
    dataset_file.write_text(
        json.dumps(
            {
                "dataset_id": "x",
                "dataset_version": "1.0.0",
                "tickets": [
                    {
                        "ticket_id": "SAMPLE-001"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetValidationError):
        load_dataset(dataset_file)


def test_dataset_validation_rejects_version_mismatch(tmp_path: Path) -> None:
    dataset_file = tmp_path / "dataset.json"
    dataset_file.write_text(
        json.dumps(
            {
                "dataset_id": "x",
                "dataset_version": "1.0.0",
                "tickets": [
                    {
                        "ticket_id": "SAMPLE-001",
                        "jira_source_data": {},
                        "expected_business_rules": [],
                        "expected_ambiguities": [],
                        "expected_missing_information": [],
                        "expected_contradictions": [],
                        "critical_scenarios": [],
                        "critical_test_cases": [],
                        "forbidden_assumptions": [],
                        "expected_acceptance_criteria_coverage": {
                            "required_items": [],
                            "minimum_coverage_ratio": 0.0
                        },
                        "evaluation_notes": "",
                        "dataset_version": "2.0.0",
                        "workspace_seed": {
                            "ticket": {},
                            "source": {
                                "description": "",
                                "comments": ""
                            },
                            "approved_test_case_structure": {
                                "main_functions": []
                            }
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetValidationError):
        load_dataset(dataset_file)
