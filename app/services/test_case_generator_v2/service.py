from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

from app.services.llm_router_service import TASK_TESTCASE_GENERATION, call_text_llm
from app.services.test_case_generator_v2.comparison import compare_generators
from app.services.test_case_generator_v2.config import (
    TestCaseGeneratorVersion,
    test_case_generator_version,
)
from app.services.test_case_generator_v2.inputs import (
    build_generator_v2_inputs,
    source_catalog,
)
from app.services.test_case_generator_v2.models import TestCaseSetV2
from app.utils.llm_json import parse_json
from app.utils.prompt_loader import load_prompt
from knowledge.storage.utils import atomic_write_json, atomic_write_text, read_json


logger = logging.getLogger(__name__)


class TestCaseGeneratorV2ValidationError(ValueError):
    pass


def _design_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "test-design"


def _write_json(path: Path, payload) -> str:
    atomic_write_json(path, payload)
    return str(path)


def _normalize_response(payload, ticket_id: str) -> dict:
    if isinstance(payload, list):
        return {
            "schema_version": "2.0",
            "generator_version": "v2",
            "ticket_id": ticket_id,
            "test_cases": payload,
        }
    if not isinstance(payload, dict):
        raise TestCaseGeneratorV2ValidationError(
            "V2 response must be an object or a test-case array"
        )
    normalized = dict(payload)
    if "test_cases" not in normalized:
        normalized["test_cases"] = normalized.get("testcases", [])
    normalized.setdefault("schema_version", "2.0")
    normalized.setdefault("generator_version", "v2")
    normalized.setdefault("ticket_id", ticket_id)
    return normalized


def _validate_traceability(result: TestCaseSetV2, inputs: dict) -> None:
    catalog = source_catalog(inputs)
    scenario_ids = {
        str(item.get("scenario_id") or "").strip()
        for item in inputs.get("scenarios", [])
        if item.get("scenario_id")
    }
    conditions = [
        item
        for item in (inputs.get("coverage_model") or {}).get("coverage_conditions", [])
        if isinstance(item, dict) and item.get("condition_id")
    ]
    coverage_ids = {str(item["condition_id"]) for item in conditions}
    mapped_coverage_ids: set[str] = set()

    errors = []
    for case in result.test_cases:
        unknown_scenarios = set(case.scenario_refs) - scenario_ids
        if unknown_scenarios:
            errors.append(
                f"{case.test_case_id}: unknown scenario refs {sorted(unknown_scenarios)}"
            )
        unknown_coverage = set(case.coverage_refs) - coverage_ids
        if unknown_coverage:
            errors.append(
                f"{case.test_case_id}: unknown coverage refs {sorted(unknown_coverage)}"
            )
        mapped_coverage_ids.update(case.coverage_refs)

        for expected in case.expected_results:
            for ref in expected.source_refs:
                key = (ref.source_type.value, ref.source_id)
                canonical = catalog.get(key)
                if ref.supports_expected_behavior() and canonical is None:
                    errors.append(
                        f"{case.test_case_id}: expected result cites unavailable source {key[0]}:{key[1]}"
                    )
                if key[0] == "KNOWLEDGE_BASE" and (
                    canonical or {}
                ).get("classification") != "ACCEPTED":
                    errors.append(
                        f"{case.test_case_id}: knowledge source {key[1]} is not accepted"
                    )

    missing_coverage = coverage_ids - mapped_coverage_ids
    if missing_coverage:
        errors.append(
            f"selected coverage conditions are not mapped: {sorted(missing_coverage)}"
        )

    if errors:
        raise TestCaseGeneratorV2ValidationError("; ".join(errors))


def _build_prompt(inputs: dict) -> str:
    template = load_prompt("prompts/generate_testcases_v2.md")
    return (
        template.replace(
            "{generator_inputs}",
            json.dumps(inputs, indent=2, ensure_ascii=False),
        ).replace(
            "{output_schema}",
            json.dumps(TestCaseSetV2.model_json_schema(), indent=2, ensure_ascii=False),
        )
    )


def generate_testcases_v2(
    state: dict,
    *,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> tuple[TestCaseSetV2, dict]:
    inputs = build_generator_v2_inputs(state)
    ticket_id = inputs["ticket_id"]
    response = call_text_llm(
        TASK_TESTCASE_GENERATION,
        _build_prompt(inputs),
        ai_mode=ai_mode or state.get("ai_mode"),
        source_channel=source_channel or state.get("source_channel"),
    )
    atomic_write_text(_design_dir(ticket_id) / "generator_v2_raw.txt", response)
    payload = _normalize_response(
        parse_json(response, label="V2 test-case generation response"),
        ticket_id,
    )
    result = TestCaseSetV2.model_validate(payload)
    _validate_traceability(result, inputs)
    return result, inputs


def select_generator_output(ticket_id: str, selection: str, selected_by: str = "manual") -> str:
    if selection not in {"v1", "v2"}:
        raise ValueError("Manual generator selection must be v1 or v2")
    path = _design_dir(ticket_id) / "generator_selection.json"
    return _write_json(
        path,
        {
            "schema_version": "1.0",
            "ticket_id": ticket_id,
            "selection": selection,
            "selected_by": selected_by,
        },
    )


def _manual_selection(ticket_id: str) -> str:
    payload = read_json(
        _design_dir(ticket_id) / "generator_selection.json",
        {"selection": "v1"},
    )
    selection = str((payload or {}).get("selection") or "v1").lower()
    return selection if selection in {"v1", "v2"} else "v1"


def run_generator_rollout(state: dict, v1_testcases: list[dict]) -> dict:
    mode = test_case_generator_version()
    if mode == TestCaseGeneratorVersion.V1:
        return {
            "test_case_generator_run": {
                "mode": mode.value,
                "v1_ran": True,
                "v2_ran": False,
                "production_generator": "v1",
            },
            "production_testcases": v1_testcases,
        }

    ticket_id = str(state.get("ticket_id") or "").strip()
    design_dir = _design_dir(ticket_id)
    _write_json(design_dir / "testcases_v1.json", v1_testcases)

    try:
        v2, inputs = generate_testcases_v2(state)
        v2_payload = v2.model_dump(mode="json")
        v2_path = _write_json(design_dir / "testcases_v2.json", v2_payload)
        from app.services.test_quality_review.service import run_test_quality_pipeline

        quality_result = run_test_quality_pipeline(
            state=state,
            inputs=inputs,
            testcases=v2,
        )
        reviewed_v2 = quality_result.pop("reviewed_testcases")
        reviewed_v2_payload = reviewed_v2.model_dump(mode="json")
        comparison = compare_generators(
            ticket_id=ticket_id,
            v1_testcases=v1_testcases,
            v2=reviewed_v2,
            inputs=inputs,
        )
        comparison_path = _write_json(
            design_dir / "generator_comparison.json", comparison
        )
    except Exception as error:
        failure = {
            "schema_version": "1.0",
            "ticket_id": ticket_id,
            "mode": mode.value,
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
        }
        _write_json(design_dir / "testcases_v2_error.json", failure)
        if mode in {
            TestCaseGeneratorVersion.V2_SHADOW,
            TestCaseGeneratorVersion.V2_MANUAL,
        }:
            logger.exception(
                "V2 test-case generation failed without affecting V1. ticket_id=%s mode=%s",
                ticket_id,
                mode.value,
            )
            return {
                "test_case_generator_run": {
                    "mode": mode.value,
                    "v1_ran": True,
                    "v2_ran": True,
                    "v2_status": "failed",
                    "production_generator": "v1",
                },
                "production_testcases": v1_testcases,
                "testcases_v2_error": failure,
            }
        raise

    production_generator = "v1"
    if mode == TestCaseGeneratorVersion.V2:
        production_generator = "v2"
    elif mode == TestCaseGeneratorVersion.V2_MANUAL:
        production_generator = _manual_selection(ticket_id)

    production_testcases = (
        reviewed_v2_payload["test_cases"] if production_generator == "v2" else v1_testcases
    )
    return {
        "test_case_generator_run": {
            "mode": mode.value,
            "v1_ran": True,
            "v2_ran": True,
            "v2_status": "succeeded",
            "production_generator": production_generator,
            "v1_artifact": str(design_dir / "testcases_v1.json"),
            "v2_artifact": v2_path,
            "comparison_artifact": comparison_path,
        },
        "production_testcases": production_testcases,
        "testcases_v2": v2_payload,
        "testcases_v2_reviewed": reviewed_v2_payload,
        "generator_comparison": comparison,
        **quality_result,
    }
