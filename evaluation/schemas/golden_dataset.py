from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class AcceptanceCriteriaExpectation(BaseModel):
    required_items: list[str] = Field(default_factory=list)
    minimum_coverage_ratio: float = 0.0

    @field_validator("minimum_coverage_ratio")
    @classmethod
    def _validate_ratio(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("minimum_coverage_ratio must be between 0 and 1")
        return value


class WorkspaceSeed(BaseModel):
    ticket: dict[str, Any]
    source: dict[str, str]
    approved_test_case_structure: dict[str, Any]


class GoldenTicket(BaseModel):
    ticket_id: str
    domain: str = "unspecified"
    jira_source_data: dict[str, Any]
    expected_business_rules: list[str] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    expected_ambiguities: list[str] = Field(default_factory=list)
    expected_missing_information: list[str] = Field(default_factory=list)
    expected_contradictions: list[str] = Field(default_factory=list)
    critical_scenarios: list[str] = Field(default_factory=list)
    critical_test_cases: list[str] = Field(default_factory=list)
    forbidden_assumptions: list[str] = Field(default_factory=list)
    expected_acceptance_criteria_coverage: AcceptanceCriteriaExpectation = Field(
        default_factory=AcceptanceCriteriaExpectation
    )
    evaluation_notes: str = ""
    expected_reference_ids: list[str] = Field(default_factory=list)
    expected_exact_codes: list[str] = Field(default_factory=list)
    dataset_version: str
    workspace_seed: WorkspaceSeed


class GoldenDataset(BaseModel):
    dataset_id: str
    dataset_version: str
    tickets: list[GoldenTicket]

    @field_validator("tickets")
    @classmethod
    def _ensure_unique_ticket_ids(cls, tickets: list[GoldenTicket]) -> list[GoldenTicket]:
        seen: set[str] = set()

        for ticket in tickets:
            if ticket.ticket_id in seen:
                raise ValueError(f"Duplicate ticket_id in dataset: {ticket.ticket_id}")
            seen.add(ticket.ticket_id)

        return tickets


class DatasetValidationError(ValueError):
    pass


def load_dataset(dataset_path: Path) -> GoldenDataset:
    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DatasetValidationError(f"Dataset file does not exist: {dataset_path}") from error
    except json.JSONDecodeError as error:
        raise DatasetValidationError(f"Dataset file is invalid JSON: {dataset_path}") from error

    try:
        dataset = GoldenDataset.model_validate(payload)
    except ValidationError as error:
        raise DatasetValidationError(f"Dataset schema validation failed: {error}") from error

    for ticket in dataset.tickets:
        if ticket.dataset_version != dataset.dataset_version:
            raise DatasetValidationError(
                "Ticket dataset_version mismatch. "
                f"ticket_id={ticket.ticket_id} "
                f"ticket.dataset_version={ticket.dataset_version} "
                f"dataset.dataset_version={dataset.dataset_version}"
            )

    return dataset
