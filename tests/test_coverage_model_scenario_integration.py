from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import test_design_workflow_service
from app.services.coverage_model.errors import CoverageModelBuildError
from app.services.coverage_model.models import (
    CoverageCondition,
    CoverageConditionType,
    CoverageModelV1,
)
from app.services.coverage_model.service import run_coverage_model_builder
from graph.nodes import generate_scenarios as scenario_node
from graph.test_generation_graph import test_generation_graph


def _approved_structure() -> dict:
    return {
        "main_functions": [
            {
                "function_id": "FUNC001",
                "related_requirement_ids": ["FR001"],
                "sub_functions": [
                    {
                        "sub_function_id": "SUB001",
                        "related_requirement_ids": ["FR001"],
                        "test_areas": [
                            {
                                "test_area_id": "CAT001",
                                "related_requirement_ids": ["FR001"],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _structure_batch() -> dict:
    return {
        "batch_id": "FUNC001_batch_1",
        "structure": _approved_structure(),
    }


def _scenario_response() -> str:
    return json.dumps(
        [
            {
                "scenario_id": "SC001",
                "function_id": "FUNC001",
                "sub_function_id": "SUB001",
                "test_area_id": "CAT001",
                "title": "Submit valid claim",
                "type": "Positive",
                "priority": "High",
                "description": "Verify a valid claim is submitted.",
                "related_requirement_ids": ["FR001"],
                "traceability": "FR001",
            }
        ]
    )


def _active_model() -> dict:
    return CoverageModelV1(
        coverage_model_id="CM-enabled",
        ticket_id="SCENARIO-1",
        requirement_refs=["FR001"],
        coverage_conditions=[
            CoverageCondition(
                condition_id="CC-mandatory",
                condition_type=CoverageConditionType.MANDATORY,
                title="Submit a valid claim",
                mandatory=True,
                rationale="Acceptance criterion",
            )
        ],
    ).model_dump(mode="json")


def _run_batch(active_model, captured_prompts: list[str]):
    original_call = scenario_node.call_text_llm
    original_save = scenario_node.save_raw_response

    def _call(*args, **kwargs):
        prompt = kwargs.get("prompt") or args[1]
        captured_prompts.append(prompt)
        return _scenario_response()

    scenario_node.call_text_llm = _call
    scenario_node.save_raw_response = lambda *args, **kwargs: "memory://raw"
    try:
        return scenario_node._generate_scenarios_for_structure_batch(
            ticket_id="SCENARIO-1",
            requirement_summary={"functional_requirements": []},
            test_scope={"scope_decision": {"positive": True}},
            requirement_items=[
                {"requirement_id": "FR001", "description": "Submit claim"}
            ],
            active_coverage_model=active_model,
            approved_structure=_approved_structure(),
            structure_batch=_structure_batch(),
            ai_mode="NO_LLM",
            source_channel="test",
        )
    finally:
        scenario_node.call_text_llm = original_call
        scenario_node.save_raw_response = original_save


def test_off_and_shadow_scenario_prompt_and_output_are_unchanged() -> None:
    captured_prompts: list[str] = []

    off_result = _run_batch(None, captured_prompts)
    shadow_result = _run_batch(None, captured_prompts)

    assert captured_prompts[0] == captured_prompts[1]
    assert "COVERAGE MODEL (enabled mode only)" not in captured_prompts[0]
    assert off_result["scenarios"] == shadow_result["scenarios"]


def test_enabled_mode_changes_prompt_but_preserves_existing_generator() -> None:
    captured_prompts: list[str] = []

    baseline_result = _run_batch(None, captured_prompts)
    enabled_result = _run_batch(_active_model(), captured_prompts)

    assert captured_prompts[0] != captured_prompts[1]
    assert "COVERAGE MODEL (enabled mode only)" in captured_prompts[1]
    assert "CC-mandatory" in captured_prompts[1]
    assert baseline_result["scenarios"] == enabled_result["scenarios"]


def test_enabled_builder_failure_raises_typed_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_MODEL_MODE", "enabled")

    def _fail(*args, **kwargs):
        raise ValueError("invalid generated model")

    monkeypatch.setattr(
        "app.services.coverage_model.service._run_active_coverage_model_builder",
        _fail,
    )

    with pytest.raises(CoverageModelBuildError, match="invalid generated model"):
        run_coverage_model_builder({"ticket_id": "FAIL-1"})

    assert (
        Path("requirements")
        / "FAIL-1"
        / "test-design"
        / "coverage_model_error.json"
    ).exists()


def test_direct_portal_workflow_builds_coverage_between_scope_and_scenarios(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        test_design_workflow_service,
        "load_approved_test_case_structure",
        lambda ticket_id: _approved_structure(),
    )
    monkeypatch.setattr(
        test_design_workflow_service,
        "load_ticket_artifacts",
        lambda ticket_id: {"analysis": {}, "requirement_summary": {}},
    )

    def _scope(state):
        calls.append("scope")
        return {"test_scope": {"scope_decision": {"positive": True}}}

    def _coverage(state):
        assert state.get("test_scope")
        calls.append("coverage")
        return {"active_coverage_model": None}

    def _scenarios(state):
        calls.append("scenarios")
        return {"scenarios": [{"scenario_id": "SC001"}]}

    monkeypatch.setattr(test_design_workflow_service, "generate_test_scope", _scope)
    monkeypatch.setattr(test_design_workflow_service, "build_coverage_model", _coverage)
    monkeypatch.setattr(test_design_workflow_service, "generate_scenarios", _scenarios)

    version = test_design_workflow_service.generate_scope_and_scenarios("DIRECT-1")

    assert version == "v1"
    assert calls == ["scope", "coverage", "scenarios"]


def test_compiled_graph_positions_coverage_before_scenarios() -> None:
    graph = test_generation_graph.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("generate_test_scope", "build_coverage_model") in edges
    assert ("build_coverage_model", "generate_scenarios") in edges
    assert ("generate_test_scope", "generate_scenarios") not in edges
