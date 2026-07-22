from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services.coverage_model.config import coverage_model_mode
from app.services.coverage_model.errors import CoverageModelConfigurationError
from app.services.coverage_model.models import CoverageModelMode, CoverageModelV1
from app.services.coverage_model.service import run_coverage_model_builder
from app.utils.artifact_loader import load_ticket_artifacts
from graph.nodes.generate_scenarios import _inject_coverage_model_context


@pytest.fixture(autouse=True)
def _clean_coverage_mode(monkeypatch):
    monkeypatch.delenv("COVERAGE_MODEL_MODE", raising=False)
    monkeypatch.delenv("COVERAGE_MODEL_ENABLED", raising=False)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _scenario_prompt() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "prompts"
        / "generate_structure_batch_scenarios.md"
    ).read_text(encoding="utf-8").rstrip("\r\n")


def _base_state(ticket_id: str) -> dict:
    return {
        "ticket_id": ticket_id,
        "analysis": {
            "requirement_items": [
                {
                    "requirement_id": "FR001",
                    "type": "Functional Requirement",
                    "description": "User submits claim successfully",
                },
                {
                    "requirement_id": "VAL001",
                    "type": "Validation",
                    "description": "Submission date must be on or after effective date 2026-01-01",
                },
                {
                    "requirement_id": "BR001",
                    "type": "Business Rule",
                    "description": "Coverage amount is 100",
                },
            ]
        },
        "requirement_summary": {
            "functional_requirements": [
                {"id": "FR001", "description": "User can submit claim", "priority": "High"}
            ],
            "business_rules": [
                {"id": "BR001", "description": "Coverage amount is 100", "priority": "High"}
            ],
            "validations": [
                {"id": "VAL001", "description": "Submission date >= effective date 2026-01-01", "priority": "High"}
            ],
            "integrations": [
                {"id": "INT001", "description": "Call third-party insurer API", "priority": "Medium"}
            ],
        },
        "test_scope": {
            "scope_decision": {
                "positive": True,
                "negative": True,
                "validation": True,
                "boundary": True,
                "business_rule": True,
                "permissions": False,
                "integration": True,
            },
            "excluded_categories": [
                {"category": "localization", "reason": "Not in this release."}
            ],
        },
        "structured_analysis": {
            "schema_version": "1.0",
            "business_rules": [
                {
                    "text": "Coverage amount is 100",
                    "confidence": 0.9,
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_DESCRIPTION",
                            "source_identifier": "DESC-1",
                        }
                    ],
                }
            ],
            "state_transitions": [
                {
                    "text": "from DRAFT to SUBMITTED",
                    "confidence": 0.8,
                    "provenance": [],
                }
            ],
            "permissions": [
                {
                    "text": "Only approver role can approve claim",
                    "confidence": 0.9,
                    "provenance": [],
                }
            ],
            "assumptions": [],
        },
        "scenarios": [
            {
                "scenario_id": "SC001",
                "title": "Submit valid claim",
                "related_requirement_ids": ["FR001"],
                "traceability": "FR001",
            }
        ],
    }


def _seed_knowledge(ticket_id: str, *, selected=None, records=None) -> None:
    base = Path("requirements") / ticket_id / "knowledge"
    _write_json(base / "selected_references.json", selected or [])
    _write_json(base / "review_records.json", records or [])


def _seed_clarifications(ticket_id: str, payload: dict) -> None:
    _write_json(Path("requirements") / ticket_id / "analysis" / "clarification_answers.json", payload)


def test_simple_positive_flow(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C1"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    result = run_coverage_model_builder(_base_state(ticket_id))
    model = result["coverage_model"]

    assert result["coverage_model_run"]["active_for_scenarios"] is True
    assert model["coverage_conditions"]
    assert any(item["condition_type"] == "MANDATORY" for item in model["coverage_conditions"])


def test_date_boundary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C2"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]

    names = {item["name"] for item in model["dimensions"]}
    assert "effective_date" in names
    assert any(item["condition_type"] == "BOUNDARY" for item in model["coverage_conditions"])


def test_permission_matrix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C3"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]
    permission_conditions = [
        item for item in model["coverage_conditions"]
        if item["condition_type"] == "PERMISSION"
    ]

    assert len(permission_conditions) >= 2


def test_state_transitions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C4"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]
    state_conditions = [
        item for item in model["coverage_conditions"]
        if item["condition_type"] == "STATE_TRANSITION"
    ]

    assert state_conditions


def test_third_party_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C5"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]
    integration_conditions = [
        item for item in model["coverage_conditions"]
        if item["condition_type"] == "INTEGRATION"
    ]

    assert any("failure" in item["title"].lower() for item in integration_conditions)


def test_historical_defect_as_regression_risk_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C6"
    _seed_knowledge(
        ticket_id,
        records=[
            {
                "source_result_id": "DEF-1:v1:chunk1",
                "classification": "HISTORICAL_CONTEXT_ONLY",
                "excerpt": "Defect: timeout caused duplicate claim",
                "citation": "DEF-1:v1:chunk1",
                "source_type": "DEFECT",
                "collection_id": "historical-defect",
            }
        ],
    )
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]

    reg = [item for item in model["coverage_conditions"] if item["condition_type"] == "REGRESSION_RISK"]
    mandatory_from_defect = [
        item for item in model["coverage_conditions"]
        if item["condition_type"] == "MANDATORY"
        and "defect" in item["title"].lower()
    ]

    assert reg
    assert not mandatory_from_defect


def test_impossible_combinations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C7"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]

    assert model["excluded_combinations"]
    assert any(item["reason"] == "impossible_combination" for item in model["excluded_combinations"])


def test_out_of_scope_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C8"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]
    out_scope = model["out_of_scope_combinations"]

    assert out_scope
    assert any(item["reason"] == "out_of_scope" for item in out_scope)


def test_no_kb_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C9"
    _seed_knowledge(ticket_id, selected=[])
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]

    assert model["coverage_conditions"]
    assert all(
        not (item["condition_type"] == "MANDATORY" and "kb-supported" in item["title"].lower())
        for item in model["coverage_conditions"]
    )


def test_shadow_isolation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "shadow")

    ticket_id = "C10"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    state = _base_state(ticket_id)
    scenarios_before = copy.deepcopy(state["scenarios"])

    result = run_coverage_model_builder(state)

    assert result["coverage_model_run"]["mode"] == "shadow"
    assert result["active_coverage_model"] is None
    assert state["scenarios"] == scenarios_before
    assert (Path("requirements") / ticket_id / "test-design" / "coverage_model.json").exists()


def test_deterministic_ids(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "enabled")

    ticket_id = "C11"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    state = _base_state(ticket_id)
    first = run_coverage_model_builder(copy.deepcopy(state))["coverage_model"]
    second = run_coverage_model_builder(copy.deepcopy(state))["coverage_model"]

    assert first["coverage_model_id"] == second["coverage_model_id"]
    assert [item["condition_id"] for item in first["coverage_conditions"]] == [
        item["condition_id"] for item in second["coverage_conditions"]
    ]


def test_feature_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "off")

    ticket_id = "C12"
    _seed_knowledge(ticket_id)
    _seed_clarifications(ticket_id, {"answered_clarifications": []})

    result = run_coverage_model_builder(_base_state(ticket_id))

    assert result["coverage_model_run"]["enabled"] is False
    assert not (Path("requirements") / ticket_id / "test-design" / "coverage_model.json").exists()


def test_rejected_kb_references_are_not_used(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    ticket_id = "C13"
    _seed_knowledge(
        ticket_id,
        selected=[
            {
                "source_result_id": "KB-REJECTED",
                "classification": "REJECTED",
                "source_type": "BUSINESS_RULE",
                "excerpt": "Rejected knowledge must never become coverage.",
            },
            {
                "source_result_id": "KB-ACCEPTED",
                "classification": "ACCEPTED",
                "source_type": "BUSINESS_RULE",
                "excerpt": "Accepted knowledge may support coverage.",
            },
        ],
    )

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]
    titles = "\n".join(item["title"] for item in model["coverage_conditions"])

    assert "Accepted knowledge" in titles
    assert "Rejected knowledge" not in titles


def test_rejected_historical_defect_is_not_used(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    ticket_id = "C13-DEFECT"
    _seed_knowledge(
        ticket_id,
        records=[
            {
                "source_result_id": "DEF-REJECTED",
                "classification": "REJECTED",
                "source_type": "DEFECT",
                "excerpt": "Rejected defect must not influence regression coverage.",
            }
        ],
    )

    model = run_coverage_model_builder(_base_state(ticket_id))["coverage_model"]

    assert all(
        "Rejected defect" not in item["title"]
        for item in model["coverage_conditions"]
    )


def test_shadow_prompt_is_byte_for_byte_unchanged(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "shadow")
    ticket_id = "C14"
    result = run_coverage_model_builder(_base_state(ticket_id))
    original_prompt = _scenario_prompt()

    assert result["active_coverage_model"] is None
    assert _inject_coverage_model_context(
        original_prompt,
        result["active_coverage_model"],
    ) == original_prompt


def test_enabled_prompt_adds_concise_coverage_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    ticket_id = "C15"
    result = run_coverage_model_builder(_base_state(ticket_id))
    original_prompt = _scenario_prompt()
    enabled_prompt = _inject_coverage_model_context(
        original_prompt,
        result["active_coverage_model"],
    )

    assert enabled_prompt != original_prompt
    assert "COVERAGE MODEL (enabled mode only)" in enabled_prompt
    assert "mandatory_conditions" in enabled_prompt
    assert "excluded_combinations" in enabled_prompt
    assert "coverage_ids" in enabled_prompt
    assert "source_excerpt" not in enabled_prompt


def test_off_mode_does_not_execute_active_builder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "off")

    def _must_not_run(*args, **kwargs):
        raise AssertionError("active coverage builder executed in off mode")

    monkeypatch.setattr(
        "app.services.coverage_model.service._run_active_coverage_model_builder",
        _must_not_run,
    )

    result = run_coverage_model_builder({"ticket_id": "C16"})

    assert result["coverage_model_run"]["status"] == "skipped"
    assert result["active_coverage_model"] is None


def test_normalized_input_produces_same_ids(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    first_state = _base_state("C17")
    second_state = copy.deepcopy(first_state)
    second_state["requirement_summary"]["business_rules"][0]["description"] = (
        "  Coverage   amount is 100  "
    )
    second_state["structured_analysis"]["business_rules"][0]["text"] = (
        "Coverage amount   is 100"
    )

    first = run_coverage_model_builder(first_state)["coverage_model"]
    second = run_coverage_model_builder(second_state)["coverage_model"]

    assert first["coverage_model_id"] == second["coverage_model_id"]
    assert [item["condition_id"] for item in first["coverage_conditions"]] == [
        item["condition_id"] for item in second["coverage_conditions"]
    ]


def test_material_coverage_change_changes_model_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    first_state = _base_state("C18")
    second_state = copy.deepcopy(first_state)
    second_state["requirement_summary"]["business_rules"].append(
        {"id": "BR002", "description": "Maximum claim amount is 500", "priority": "High"}
    )

    first = run_coverage_model_builder(first_state)["coverage_model"]
    second = run_coverage_model_builder(second_state)["coverage_model"]

    assert first["coverage_model_id"] != second["coverage_model_id"]


def test_duplicate_conditions_are_deduplicated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    state = _base_state("C19")
    state["requirement_summary"]["business_rules"].append(
        {"id": "BR-DUP", "description": " coverage amount  is 100 ", "priority": "High"}
    )

    model = run_coverage_model_builder(state)["coverage_model"]
    condition_ids = [item["condition_id"] for item in model["coverage_conditions"]]

    assert len(condition_ids) == len(set(condition_ids))


def test_unresolved_information_becomes_question(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    state = _base_state("C20")
    state["clarifications"] = {
        "clarification_questions": [
            {"question_id": "Q001", "question": "Which timezone applies?"}
        ]
    }
    state["clarification_answers"] = {"answers": []}

    model = run_coverage_model_builder(state)["coverage_model"]

    assert model["uncovered_questions"] == ["Which timezone applies?"]
    assert all(
        "timezone" not in item["title"].casefold()
        for item in model["coverage_conditions"]
    )


def test_old_state_and_workspace_without_coverage_remain_valid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "off")
    ticket_id = "C21"
    (Path("requirements") / ticket_id).mkdir(parents=True)

    result = run_coverage_model_builder({"ticket_id": ticket_id})
    artifacts = load_ticket_artifacts(ticket_id)

    assert result["coverage_model_run"]["mode"] == "off"
    assert artifacts["coverage_model"] == {}
    assert artifacts["coverage_analysis"] == ""


def test_shadow_failure_records_diagnostic_and_continues(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "shadow")

    def _fail(*args, **kwargs):
        raise RuntimeError("deterministic shadow failure")

    monkeypatch.setattr(
        "app.services.coverage_model.service._run_active_coverage_model_builder",
        _fail,
    )
    result = run_coverage_model_builder({"ticket_id": "C22"})

    assert result["coverage_model_run"]["status"] == "failed"
    assert result["active_coverage_model"] is None
    assert "deterministic shadow failure" in result["coverage_model_error"]["error"]
    assert (Path("requirements") / "C22" / "test-design" / "coverage_model_error.json").exists()


def test_invalid_configuration_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "sometimes")

    with pytest.raises(CoverageModelConfigurationError, match="Allowed values"):
        coverage_model_mode()


def test_legacy_configuration_mapping_remains_compatible(monkeypatch) -> None:
    monkeypatch.setenv("COVERAGE_MODEL_ENABLED", "true")

    assert coverage_model_mode() == CoverageModelMode.ENABLED


def test_artifacts_validate_against_schema_and_markdown_sections(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")
    ticket_id = "C23"

    result = run_coverage_model_builder(_base_state(ticket_id))
    model_file = Path("requirements") / ticket_id / "test-design" / "coverage_model.json"
    markdown_file = Path("requirements") / ticket_id / "test-design" / "coverage_analysis.md"
    validated = CoverageModelV1.model_validate(json.loads(model_file.read_text(encoding="utf-8")))
    markdown = markdown_file.read_text(encoding="utf-8")

    assert validated.ticket_id == ticket_id
    assert validated.generation_metadata["full_cartesian_product_generated"] is False
    for heading in (
        "## Selected Dimensions",
        "## Mandatory Coverage",
        "## Boundary Conditions",
        "## Negative Paths",
        "## Integration Failures",
        "## Regression Risks",
        "## Excluded Combinations",
        "## Unresolved Questions",
        "## Source Traceability",
    ):
        assert heading in markdown
    assert result["coverage_model"]["version"] == "1.0"
