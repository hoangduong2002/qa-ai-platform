import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_router_service import (
    TASK_TESTCASE_IMPROVEMENT,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import (
    save_improved_testcases,
    save_raw_response,
    save_testcases,
)
from app.utils.test_structure_store import load_approved_test_case_structure
from app.utils.function_improve_store import (
    save_function_improved_testcases,
    save_function_improve_manifest,
)


logger = logging.getLogger(__name__)


def _resolve_ai_mode(state: dict | None = None) -> str | None:
    state = state or {}
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def _short_error(
    error: Exception,
    max_length: int = 300,
) -> str:
    text = str(error)

    if not text:
        return type(error).__name__

    first_line = text.splitlines()[0]

    if len(first_line) > max_length:
        return first_line[:max_length] + "..."

    return first_line


def _log_function_improve_fallback(
    ticket_id: str,
    function_id: str,
    error_file: str,
    error: Exception,
) -> None:
    logger.warning(
        "Function improve failed; fallback will be used. "
        "ticket_id=%s, function_id=%s, error_file=%s, error=%s",
        ticket_id,
        function_id,
        error_file,
        _short_error(error),
    )


def normalize_testcases(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in [
            "testcases",
            "test_cases",
            "improved_testcases",
            "improved_test_cases",
            "testCases",
        ]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(
        "Invalid improved testcases JSON format. "
        "Expected list or object with testcases/improved_testcases key."
    )


def _as_list(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _unique_ids(values: list) -> list[str]:
    result = []
    seen = set()

    for value in values:
        if not value:
            continue

        if not isinstance(value, str):
            value = str(value)

        clean_value = value.strip()

        if not clean_value:
            continue

        if clean_value not in seen:
            seen.add(clean_value)
            result.append(clean_value)

    return result


def _normalize_requirement_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    if isinstance(value, list):
        return _unique_ids(value)

    return []


def _get_related_requirement_ids(item: dict) -> list[str]:
    if not isinstance(item, dict):
        return []

    return _unique_ids(
        _as_list(item.get("related_requirement_ids"))
        + _as_list(item.get("requirement_ids"))
        + _as_list(item.get("related_requirements"))
    )


def _normalize_list_field(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        return [value]

    return [str(value)]


ALLOWED_TEST_DESIGN_TECHNIQUES = {
    "EP",
    "BVA",
    "Decision Table",
    "State Transition",
    "Pairwise",
    "Error Guessing",
    "Use Case",
    "Security",
    "UX",
}


def _infer_technique_from_type(testcase_type: str) -> str:
    normalized_type = str(testcase_type or "").strip().lower()

    if normalized_type in ["boundary", "boundary value", "bva"]:
        return "BVA"

    if normalized_type in ["business rule", "decision", "decision table"]:
        return "Decision Table"

    if normalized_type in ["state", "state transition", "workflow"]:
        return "State Transition"

    if normalized_type in ["security", "permission", "permissions"]:
        return "Security"

    if normalized_type in ["ux", "ui", "ux_ui", "usability"]:
        return "UX"

    if normalized_type in ["positive", "negative", "validation"]:
        return "EP"

    return "Use Case"


def _normalize_technique(
    technique: Any,
    testcase_type: str = "",
) -> str:
    if technique is None:
        return _infer_technique_from_type(testcase_type)

    value = str(technique).strip()

    aliases = {
        "equivalence partitioning": "EP",
        "equivalence partition": "EP",
        "ep": "EP",
        "boundary value analysis": "BVA",
        "boundary value": "BVA",
        "bva": "BVA",
        "decision table testing": "Decision Table",
        "decision table": "Decision Table",
        "state transition testing": "State Transition",
        "state transition": "State Transition",
        "pairwise testing": "Pairwise",
        "pairwise": "Pairwise",
        "combinatorial": "Pairwise",
        "error guessing": "Error Guessing",
        "use case": "Use Case",
        "use-case": "Use Case",
        "security": "Security",
        "ux": "UX",
        "ui": "UX",
        "usability": "UX",
    }

    normalized = aliases.get(value.lower(), value)

    if normalized in ALLOWED_TEST_DESIGN_TECHNIQUES:
        return normalized

    return _infer_technique_from_type(testcase_type)


def _get_testcase_id(testcase: dict) -> str:
    if not isinstance(testcase, dict):
        return ""

    return testcase.get("testcase_id") or testcase.get("id") or ""


def _get_next_testcase_number(testcases: list) -> int:
    max_number = 0

    for testcase in testcases:
        testcase_id = _get_testcase_id(testcase)

        if not testcase_id:
            continue

        if not testcase_id.startswith("TC"):
            continue

        number_part = testcase_id[2:]

        if not number_part.isdigit():
            continue

        max_number = max(max_number, int(number_part))

    return max_number + 1


def _is_valid_testcase_item(item: dict) -> bool:
    if not isinstance(item, dict):
        return False

    if not item.get("testcase_id"):
        return False

    if not item.get("scenario_id"):
        return False

    if not item.get("function_id"):
        return False

    if not item.get("test_area_id"):
        return False

    if not item.get("title"):
        return False

    if not item.get("technique"):
        return False

    if not item.get("test_steps"):
        return False

    if not item.get("expected_results"):
        return False

    if not item.get("related_requirement_ids"):
        return False

    return True


def _validate_original_testcases(original_testcases: list) -> None:
    if not original_testcases:
        raise ValueError(
            "Original testcases is empty before improve. "
            "Improve step must receive the full generated test suite."
        )

    invalid_items = [
        item for item in original_testcases
        if not isinstance(item, dict) or not item.get("testcase_id")
    ]

    if invalid_items:
        raise ValueError(
            f"Original testcases contains invalid item: {invalid_items[0]}"
        )


def _build_scenario_index(scenarios: list) -> dict:
    """
    Build scenario_id -> metadata index.

    Improve patch can be compact:
    - scenario_id
    - title
    - type
    - priority
    - preconditions
    - steps
    - expected

    Metadata is derived from scenario_id.
    """

    index = {}

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue

        scenario_id = scenario.get("scenario_id")

        if not scenario_id:
            continue

        related_requirement_ids = _normalize_requirement_ids(
            scenario.get("related_requirement_ids")
        )

        index[scenario_id] = {
            "scenario_id": scenario_id,
            "function_id": scenario.get("function_id", ""),
            "sub_function_id": scenario.get("sub_function_id", ""),
            "test_area_id": scenario.get("test_area_id", ""),
            "related_requirement_ids": related_requirement_ids,
            "traceability": (
                scenario.get("traceability")
                or ", ".join(related_requirement_ids)
            ),
        }

    return index


def _build_testcase_index(testcases: list) -> dict:
    index = {}

    for testcase in testcases:
        if not isinstance(testcase, dict):
            continue

        testcase_id = testcase.get("testcase_id")

        if not testcase_id:
            continue

        index[testcase_id] = testcase

    return index


def _normalize_compact_patch_testcase(
    testcase: dict,
    scenario_index: dict,
    original_testcase_index: dict,
) -> dict:
    """
    Normalize compact improve patch into internal schema.

    Priority for metadata enrichment:
    1. scenario_id from scenario_index
    2. original testcase by testcase_id
    3. fallback to any field already provided by patch

    This prevents improved patches from wiping out function_id,
    sub_function_id, test_area_id, and traceability.
    """

    if not isinstance(testcase, dict):
        return {}

    testcase_id = testcase.get("testcase_id", "")
    original_testcase = original_testcase_index.get(testcase_id, {})

    scenario_id = (
        testcase.get("scenario_id")
        or original_testcase.get("scenario_id")
        or ""
    )

    # Reject fake or hallucinated scenario ids.
    if str(scenario_id).startswith("MISS_SC_"):
        scenario_id = original_testcase.get("scenario_id", "")

    scenario_info = scenario_index.get(scenario_id, {})

    # If patch changed scenario_id to an unknown scenario, preserve original.
    if scenario_id and not scenario_info and original_testcase:
        original_scenario_id = original_testcase.get("scenario_id", "")
        original_scenario_info = scenario_index.get(original_scenario_id, {})

        if original_scenario_info:
            scenario_id = original_scenario_id
            scenario_info = original_scenario_info

    related_requirement_ids = (
        testcase.get("related_requirement_ids")
        or testcase.get("requirement_ids")
        or scenario_info.get("related_requirement_ids")
        or original_testcase.get("related_requirement_ids")
        or []
    )

    related_requirement_ids = _normalize_requirement_ids(
        related_requirement_ids
    )

    test_steps = (
        testcase.get("steps")
        or testcase.get("test_steps")
        or original_testcase.get("test_steps")
        or []
    )

    expected_results = (
        testcase.get("expected")
        or testcase.get("expected_results")
        or original_testcase.get("expected_results")
        or []
    )

    testcase_type = (
        testcase.get("type")
        or original_testcase.get("type")
        or ""
    )

    return {
        "testcase_id": testcase_id,
        "scenario_id": scenario_id,
        "function_id": (
            testcase.get("function_id")
            or scenario_info.get("function_id")
            or original_testcase.get("function_id")
            or ""
        ),
        "sub_function_id": (
            testcase.get("sub_function_id")
            or scenario_info.get("sub_function_id")
            or original_testcase.get("sub_function_id")
            or ""
        ),
        "test_area_id": (
            testcase.get("test_area_id")
            or scenario_info.get("test_area_id")
            or original_testcase.get("test_area_id")
            or ""
        ),
        "title": (
            testcase.get("title")
            or original_testcase.get("title")
            or ""
        ),
        "type": testcase_type,
        "technique": _normalize_technique(
            testcase.get("technique")
            or original_testcase.get("technique"),
            testcase_type,
        ),
        "priority": (
            testcase.get("priority")
            or original_testcase.get("priority")
            or ""
        ),
        "preconditions": _normalize_list_field(
            testcase.get("preconditions")
            or original_testcase.get("preconditions")
            or []
        ),
        "test_steps": _normalize_list_field(test_steps),
        "expected_results": _normalize_list_field(expected_results),
        "related_requirement_ids": related_requirement_ids,
        "traceability": (
            testcase.get("traceability")
            or scenario_info.get("traceability")
            or original_testcase.get("traceability")
            or ", ".join(related_requirement_ids)
        ),
    }


def _normalize_compact_patch_testcases(
    patch_testcases: list,
    scenarios: list,
    original_testcases: list,
) -> list:
    scenario_index = _build_scenario_index(scenarios)
    original_testcase_index = _build_testcase_index(original_testcases)

    normalized = []

    for patch_item in patch_testcases:
        normalized_item = _normalize_compact_patch_testcase(
            testcase=patch_item,
            scenario_index=scenario_index,
            original_testcase_index=original_testcase_index,
        )

        if normalized_item:
            normalized.append(normalized_item)

    return normalized


def _normalize_patch_testcase(
    testcase: dict,
    next_id_number: int,
) -> tuple[dict, int]:
    item = dict(testcase)

    if not item.get("testcase_id") or str(item.get("testcase_id")).startswith("NEW_TC"):
        item["testcase_id"] = f"TC{next_id_number:03d}"
        next_id_number += 1

    related_requirement_ids = _get_related_requirement_ids(item)

    if related_requirement_ids:
        item["related_requirement_ids"] = related_requirement_ids

        if not item.get("traceability"):
            item["traceability"] = ", ".join(related_requirement_ids)

    return item, next_id_number


def merge_improved_testcases(
    original_testcases: list,
    improved_patch_testcases: list,
) -> list:
    """
    Merge patch-style improved test cases into the original suite.

    Rules:
    - Original test cases are the source of truth.
    - If improved item has an existing testcase_id, replace that testcase only.
    - If improved item has a new testcase_id, append as new test case.
    - If improved item has no testcase_id, assign a new testcase_id and append.
    - Never drop unchanged original test cases.
    """

    _validate_original_testcases(original_testcases)

    testcase_map = {}
    original_order = []

    for testcase in original_testcases:
        testcase_id = _get_testcase_id(testcase)

        if not testcase_id:
            continue

        testcase_map[testcase_id] = dict(testcase)
        original_order.append(testcase_id)

    next_id_number = _get_next_testcase_number(original_testcases)
    appended_ids = []

    for patch_item in improved_patch_testcases:
        if not isinstance(patch_item, dict):
            logger.warning(
                "Skipping invalid improved testcase patch item: %s",
                patch_item,
            )
            continue

        patch_item, next_id_number = _normalize_patch_testcase(
            patch_item,
            next_id_number,
        )

        testcase_id = patch_item["testcase_id"]

        if testcase_id in testcase_map:
            existing = testcase_map[testcase_id]

            merged_item = dict(existing)

            for key, value in patch_item.items():
                if value in ["", None, [], {}]:
                    continue

                merged_item[key] = value

            testcase_map[testcase_id] = merged_item
        else:
            testcase_map[testcase_id] = patch_item
            appended_ids.append(testcase_id)

    merged = []

    for testcase_id in original_order:
        if testcase_id in testcase_map:
            merged.append(testcase_map[testcase_id])

    for testcase_id in appended_ids:
        if testcase_id in testcase_map:
            merged.append(testcase_map[testcase_id])

    if len(merged) < len(original_testcases):
        raise ValueError(
            "Improved test suite is smaller than original test suite. "
            f"Original count={len(original_testcases)}, merged count={len(merged)}. "
            "Improve step is not allowed to drop existing test cases."
        )

    return merged


def validate_merged_testcases(
    original_testcases: list,
    merged_testcases: list,
) -> None:
    if len(merged_testcases) < len(original_testcases):
        raise ValueError(
            "Merged improved testcases count is smaller than original count. "
            f"Original={len(original_testcases)}, merged={len(merged_testcases)}"
        )

    invalid_items = []

    for item in merged_testcases:
        if not _is_valid_testcase_item(item):
            invalid_items.append(item)

    if invalid_items:
        raise ValueError(
            f"Merged improved testcases contains invalid item: {invalid_items[0]}"
        )


def repair_json_with_llm(
    ticket_id: str,
    malformed_json_text: str,
    original_error: Exception,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    """
    Ask LLM to repair malformed JSON output once.

    This is used only as a fallback when parse_json() fails.
    The repaired response is still parsed and validated by the normal pipeline.
    """

    logger.info(
        "Attempting to repair malformed improve JSON. ticket_id=%s, error=%s",
        ticket_id,
        _short_error(original_error),
    )

    repair_prompt = f"""
You are a JSON repair tool.

Fix the malformed JSON below.

Rules:
- Return ONLY valid JSON.
- Return a JSON array.
- Do not add explanation.
- Do not use markdown.
- Do not wrap in ```json.
- Preserve all fields and values as much as possible.
- Fix missing quotes.
- Fix unescaped newlines inside strings.
- Fix trailing commas.
- Do not invent new test cases.
- Do not remove valid test cases.

Original parse error:
{original_error}

Malformed JSON:
{malformed_json_text}
"""

    response_content = call_text_llm(
        TASK_TESTCASE_IMPROVEMENT,
        repair_prompt,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )

    repaired_raw_file = save_raw_response(
        ticket_id,
        "improve_testcases_repaired_raw",
        response_content,
    )

    logger.info(
        "Repaired improve JSON response saved. ticket_id=%s, file=%s",
        ticket_id,
        repaired_raw_file,
    )

    return parse_json(response_content)


def _extract_functions(approved_structure: dict) -> list[dict]:
    if not isinstance(approved_structure, dict):
        return []

    functions = (
        approved_structure.get("main_functions")
        or approved_structure.get("functions")
        or approved_structure.get("test_functions")
        or []
    )

    if not isinstance(functions, list):
        return []

    return functions


def _get_function_id(function_item: dict) -> str:
    if not isinstance(function_item, dict):
        return ""

    return (
        function_item.get("function_id")
        or function_item.get("main_function_id")
        or function_item.get("id")
        or ""
    )


def _get_function_name(function_item: dict) -> str:
    if not isinstance(function_item, dict):
        return ""

    return (
        function_item.get("name")
        or function_item.get("title")
        or function_item.get("function_name")
        or ""
    )


def _get_item_function_id(item: dict) -> str:
    if not isinstance(item, dict):
        return ""

    return (
        item.get("function_id")
        or item.get("main_function_id")
        or ""
    )


def _scenario_matches_function_by_requirement(
    scenario: dict,
    function_item: dict,
) -> bool:
    scenario_requirement_ids = set(_get_related_requirement_ids(scenario))
    function_requirement_ids = set(_get_related_requirement_ids(function_item))

    if not scenario_requirement_ids or not function_requirement_ids:
        return False

    return bool(scenario_requirement_ids.intersection(function_requirement_ids))


def _testcase_matches_function_by_requirement(
    testcase: dict,
    function_item: dict,
) -> bool:
    testcase_requirement_ids = set(_get_related_requirement_ids(testcase))
    function_requirement_ids = set(_get_related_requirement_ids(function_item))

    if not testcase_requirement_ids or not function_requirement_ids:
        return False

    return bool(testcase_requirement_ids.intersection(function_requirement_ids))


def _group_items_by_function(
    functions: list[dict],
    scenarios: list,
    testcases: list,
) -> tuple[dict[str, dict], list, list]:
    groups = {}
    function_by_id = {}

    for function_item in functions:
        function_id = _get_function_id(function_item)

        if not function_id:
            continue

        function_by_id[function_id] = function_item
        groups[function_id] = {
            "function": function_item,
            "scenarios": [],
            "testcases": [],
        }

    unmatched_scenarios = []
    unmatched_testcases = []

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            unmatched_scenarios.append(scenario)
            continue

        function_id = _get_item_function_id(scenario)

        if function_id and function_id in groups:
            groups[function_id]["scenarios"].append(scenario)
            continue

        matched_function_id = None

        for candidate_function_id, function_item in function_by_id.items():
            if _scenario_matches_function_by_requirement(
                scenario,
                function_item,
            ):
                matched_function_id = candidate_function_id
                break

        if matched_function_id:
            scenario["function_id"] = matched_function_id
            groups[matched_function_id]["scenarios"].append(scenario)
        else:
            unmatched_scenarios.append(scenario)

    for testcase in testcases:
        if not isinstance(testcase, dict):
            unmatched_testcases.append(testcase)
            continue

        function_id = _get_item_function_id(testcase)

        if function_id and function_id in groups:
            groups[function_id]["testcases"].append(testcase)
            continue

        matched_function_id = None

        for candidate_function_id, function_item in function_by_id.items():
            if _testcase_matches_function_by_requirement(
                testcase,
                function_item,
            ):
                matched_function_id = candidate_function_id
                break

        if matched_function_id:
            testcase["function_id"] = matched_function_id
            groups[matched_function_id]["testcases"].append(testcase)
        else:
            unmatched_testcases.append(testcase)

    return groups, unmatched_scenarios, unmatched_testcases


def _get_function_coverage_review(
    coverage_review: dict,
    function_id: str,
) -> dict:
    if not isinstance(coverage_review, dict):
        return {}

    for review in coverage_review.get("function_reviews", []):
        if isinstance(review, dict) and review.get("function_id") == function_id:
            return review

    return {
        "function_id": function_id,
        "coverage_score": coverage_review.get("coverage_score"),
        "summary": coverage_review.get("summary", ""),
        "missing_scenarios": [
            item for item in coverage_review.get("missing_scenarios", [])
            if isinstance(item, dict) and item.get("function_id") == function_id
        ],
        "weak_testcases": [
            item for item in coverage_review.get("weak_testcases", [])
            if isinstance(item, dict) and item.get("function_id") == function_id
        ],
        "missing_testcases": [
            item for item in coverage_review.get("missing_testcases", [])
            if isinstance(item, dict) and item.get("function_id") == function_id
        ],
        "traceability_issues": [
            item for item in coverage_review.get("traceability_issues", [])
            if isinstance(item, dict) and item.get("function_id") == function_id
        ],
        "recommendations": [
            item for item in coverage_review.get("recommendations", [])
            if isinstance(item, dict) and item.get("function_id") == function_id
        ],
    }


def _get_parallel_workers(function_count: int) -> int:
    configured_value = os.getenv("IMPROVE_TESTCASE_PARALLEL_WORKERS", "3")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid IMPROVE_TESTCASE_PARALLEL_WORKERS value: %s. Falling back to 3.",
            configured_value,
        )
        configured_workers = 3

    configured_workers = max(configured_workers, 1)
    return min(function_count, configured_workers)


def _is_fail_fast_improve_enabled() -> bool:
    value = os.getenv("IMPROVE_FAIL_FAST", "false")
    return value.strip().lower() in ["1", "true", "yes", "y"]


def _is_improve_json_repair_enabled() -> bool:
    return os.getenv("IMPROVE_JSON_REPAIR_ENABLED", "false").lower() in [
        "1",
        "true",
        "yes",
        "y",
    ]


def _build_fallback_improve_result(
    function_id: str,
    function_item: dict,
    function_testcases: list,
    error: Exception,
) -> dict:
    logger.info(
        "Using original test cases as fallback. function_id=%s, error=%s",
        function_id,
        _short_error(error),
    )

    return {
        "function_id": function_id,
        "function_name": _get_function_name(function_item),
        "original_count": len(function_testcases),
        "patch_count": 0,
        "improved_count": len(function_testcases),
        "patch_testcases": [],
        "improved_testcases": function_testcases,
        "file": "",
        "raw_file": "",
        "fallback_used": True,
        "fallback_reason": str(error),
    }


def _build_function_improve_prompt(
    requirement_summary: dict,
    test_scope: dict,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
    function_coverage_review: dict,
    review_comments: list,
) -> str:
    prompt = load_prompt("prompts/improve_function_testcases.md")

    return (
        prompt
        .replace(
            "{requirement_summary}",
            json.dumps(
                requirement_summary,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{test_scope}",
            json.dumps(
                test_scope,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{main_function}",
            json.dumps(
                function_item,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{function_scenarios}",
            json.dumps(
                function_scenarios,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{function_testcases}",
            json.dumps(
                function_testcases,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{function_coverage_review}",
            json.dumps(
                function_coverage_review,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{review_comments}",
            json.dumps(
                review_comments,
                indent=2,
                ensure_ascii=False,
            ),
        )
    )


def _has_actionable_improve_items(
    function_coverage_review: dict,
    review_comments: list,
) -> bool:
    if review_comments:
        return True

    if not isinstance(function_coverage_review, dict):
        return False

    actionable_keys = [
        "missing_scenarios",
        "weak_testcases",
        "missing_testcases",
        "traceability_issues",
        "recommendations",
    ]

    return any(
        bool(function_coverage_review.get(key))
        for key in actionable_keys
    )


def _extract_impacted_testcase_ids(
    function_coverage_review: dict,
) -> set[str]:
    impacted = set()

    if not isinstance(function_coverage_review, dict):
        return impacted

    for item in function_coverage_review.get("weak_testcases", []):
        if isinstance(item, dict) and item.get("testcase_id"):
            impacted.add(item["testcase_id"])

    for item in function_coverage_review.get("traceability_issues", []):
        if isinstance(item, dict):
            item_id = item.get("item_id") or item.get("testcase_id")
            if item_id:
                impacted.add(item_id)

    for rec in function_coverage_review.get("recommendations", []):
        if not isinstance(rec, dict):
            continue

        for testcase_id in rec.get("related_testcase_ids", []):
            if testcase_id:
                impacted.add(testcase_id)

    return impacted


def _extract_impacted_scenario_ids(
    function_coverage_review: dict,
) -> set[str]:
    impacted = set()

    if not isinstance(function_coverage_review, dict):
        return impacted

    for item in function_coverage_review.get("missing_scenarios", []):
        if isinstance(item, dict) and item.get("scenario_id"):
            impacted.add(item["scenario_id"])

    for rec in function_coverage_review.get("recommendations", []):
        if not isinstance(rec, dict):
            continue

        for scenario_id in rec.get("related_scenario_ids", []):
            if scenario_id:
                impacted.add(scenario_id)

    return impacted


def _generate_improve_patch_for_function(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    function_id: str,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
    function_coverage_review: dict,
    review_comments: list,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> dict:
    logger.info(
        "Starting function-level improve. ticket_id=%s, function_id=%s, testcase_count=%s",
        ticket_id,
        function_id,
        len(function_testcases),
    )

    impacted_testcase_ids = _extract_impacted_testcase_ids(
        function_coverage_review
    )

    impacted_scenario_ids = _extract_impacted_scenario_ids(
        function_coverage_review
    )

    target_testcases = [
        testcase
        for testcase in function_testcases
        if testcase.get("testcase_id") in impacted_testcase_ids
    ]

    target_scenarios = [
        scenario
        for scenario in function_scenarios
        if scenario.get("scenario_id") in impacted_scenario_ids
    ]

    if review_comments and not target_testcases and not target_scenarios:
        target_testcases = function_testcases[:10]
        target_scenarios = function_scenarios[:10]

    final_prompt = _build_function_improve_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=target_scenarios,
        function_testcases=target_testcases,
        function_coverage_review=function_coverage_review,
        review_comments=review_comments,
    )

    response_content = call_text_llm(
        TASK_TESTCASE_IMPROVEMENT,
        final_prompt,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )

    raw_file = save_raw_response(
        ticket_id,
        f"improve_testcases_{function_id}_raw",
        response_content,
    )

    try:
        try:
            parsed = parse_json(response_content)
        except Exception as parse_error:
            if _is_improve_json_repair_enabled():
                parsed = repair_json_with_llm(
                    ticket_id=ticket_id,
                    malformed_json_text=response_content,
                    original_error=parse_error,
                    ai_mode=ai_mode,
                    source_channel=source_channel,
                )
            else:
                raise

        raw_patch_testcases = normalize_testcases(parsed)

        patch_testcases = _normalize_compact_patch_testcases(
        patch_testcases=raw_patch_testcases,
        scenarios=function_scenarios,
        original_testcases=function_testcases,
    )

    except Exception as error:
        error_file = save_raw_response(
            ticket_id,
            f"improve_testcases_{function_id}_parse_error",
            (
                f"Failed to parse improve response for {function_id}.\n\n"
                f"Function:\n"
                f"{json.dumps(function_item, indent=2, ensure_ascii=False)}\n\n"
                f"Original Function Test Cases:\n"
                f"{json.dumps(function_testcases, indent=2, ensure_ascii=False)}\n\n"
                f"Coverage Review:\n"
                f"{json.dumps(function_coverage_review, indent=2, ensure_ascii=False)}\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        if _is_fail_fast_improve_enabled():
            logger.exception(
                "Function-level improve failed. ticket_id=%s, function_id=%s",
                ticket_id,
                function_id,
            )
        else:
            _log_function_improve_fallback(
                ticket_id=ticket_id,
                function_id=function_id,
                error_file=error_file,
                error=error,
            )

        raise ValueError(
            f"Failed to improve test cases for {function_id}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    save_raw_response(
        ticket_id,
        f"improve_testcases_{function_id}_patch",
        json.dumps(
            patch_testcases,
            indent=2,
            ensure_ascii=False,
        ),
    )

    improved_function_testcases = merge_improved_testcases(
        original_testcases=function_testcases,
        improved_patch_testcases=patch_testcases,
    )

    validate_merged_testcases(
        original_testcases=function_testcases,
        merged_testcases=improved_function_testcases,
    )

    improved_function_file = save_function_improved_testcases(
        ticket_id=ticket_id,
        function_id=function_id,
        testcases=improved_function_testcases,
    )

    logger.info(
        "Function-level improve completed. ticket_id=%s, function_id=%s, original_count=%s, patch_count=%s, improved_count=%s, file=%s",
        ticket_id,
        function_id,
        len(function_testcases),
        len(patch_testcases),
        len(improved_function_testcases),
        improved_function_file,
    )

    return {
        "function_id": function_id,
        "function_name": _get_function_name(function_item),
        "original_count": len(function_testcases),
        "patch_count": len(patch_testcases),
        "improved_count": len(improved_function_testcases),
        "patch_testcases": patch_testcases,
        "improved_testcases": improved_function_testcases,
        "file": improved_function_file,
        "raw_file": raw_file,
    }


def _renumber_master_testcases(testcases: list) -> list:
    renumbered = []

    for index, testcase in enumerate(testcases, start=1):
        item = dict(testcase)
        item["testcase_id"] = f"TC{index:03d}"
        renumbered.append(item)

    return renumbered


def _validate_no_duplicate_testcase_ids(testcases: list) -> None:
    seen = set()
    duplicated = []

    for testcase in testcases:
        if not isinstance(testcase, dict):
            continue

        testcase_id = testcase.get("testcase_id")

        if not testcase_id:
            continue

        if testcase_id in seen:
            duplicated.append(testcase_id)
        else:
            seen.add(testcase_id)

    if duplicated:
        raise ValueError(
            "Duplicate testcase_id detected after function improve merge: "
            f"{sorted(set(duplicated))[:20]}"
        )


def _deduplicate_function_results(
    function_results: list[dict],
) -> list[dict]:
    deduplicated = {}
    duplicate_counts = {}

    for result in function_results:
        function_id = result.get("function_id")

        if not function_id:
            continue

        if function_id in deduplicated:
            duplicate_counts[function_id] = (
                duplicate_counts.get(function_id, 1) + 1
            )

        deduplicated[function_id] = result

    if duplicate_counts:
        logger.warning(
            "Duplicate function improve results detected and deduplicated: %s",
            duplicate_counts,
        )

    return [
        deduplicated[function_id]
        for function_id in sorted(deduplicated.keys())
    ]


def improve_testcases(state):
    ticket_id = state["ticket_id"]
    ai_mode = _resolve_ai_mode(state)
    source_channel = state.get("source_channel")

    original_testcases = state.get("testcases", [])
    improve_version = state.get("improve_version", "latest")

    logger.info(
        "Starting function-based test case improvement. ticket_id=%s, original_count=%s, version=%s",
        ticket_id,
        len(original_testcases),
        improve_version,
    )

    _validate_original_testcases(original_testcases)

    approved_structure = (
        state.get("approved_test_case_structure")
        or load_approved_test_case_structure(ticket_id)
    )

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for function-based improve."
        )

    functions = _extract_functions(approved_structure)

    if not functions:
        raise ValueError(
            "No main functions found in approved_test_case_structure. "
            "Expected key: main_functions or functions."
        )

    scenarios = state.get("scenarios", [])
    coverage_review = state.get("coverage_review", {})
    review_comments = state.get("review_comments", [])

    groups, unmatched_scenarios, unmatched_testcases = _group_items_by_function(
        functions=functions,
        scenarios=scenarios,
        testcases=original_testcases,
    )

    if unmatched_scenarios:
        unmatched_file = save_raw_response(
            ticket_id,
            "improve_testcases_unmatched_scenarios",
            json.dumps(
                unmatched_scenarios,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some scenarios cannot be mapped to a main function during improve.\n"
            f"Unmatched scenarios saved to: {unmatched_file}"
        )

    if unmatched_testcases:
        unmatched_file = save_raw_response(
            ticket_id,
            "improve_testcases_unmatched_testcases",
            json.dumps(
                unmatched_testcases,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some test cases cannot be mapped to a main function during improve.\n"
            f"Unmatched test cases saved to: {unmatched_file}"
        )

    executable_groups = {
        function_id: group
        for function_id, group in groups.items()
        if group.get("testcases")
    }

    if not executable_groups:
        raise ValueError(
            "No test cases could be grouped by main function for improve."
        )

    worker_count = _get_parallel_workers(len(executable_groups))

    logger.info(
        "Grouped test cases for function-level improve. ticket_id=%s, function_count=%s, worker_count=%s",
        ticket_id,
        len(executable_groups),
        worker_count,
    )

    function_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {}

        for function_id, group in executable_groups.items():
            function_coverage_review = _get_function_coverage_review(
                coverage_review,
                function_id,
            )

            if not _has_actionable_improve_items(
                function_coverage_review,
                review_comments,
            ):
                function_results.append(
                    {
                        "function_id": function_id,
                        "function_name": _get_function_name(group["function"]),
                        "original_count": len(group["testcases"]),
                        "patch_count": 0,
                        "improved_count": len(group["testcases"]),
                        "patch_testcases": [],
                        "improved_testcases": group["testcases"],
                        "file": "",
                        "raw_file": "",
                        "skipped": True,
                        "skip_reason": "No actionable coverage review items.",
                    }
                )
                continue

            future = executor.submit(
                _generate_improve_patch_for_function,
                ticket_id,
                state.get("requirement_summary", {}),
                state.get("test_scope", {}),
                function_id,
                group["function"],
                group["scenarios"],
                group["testcases"],
                function_coverage_review,
                review_comments,
                ai_mode,
                source_channel,
            )

            future_map[future] = function_id

        for future in as_completed(future_map):
            function_id = future_map[future]

            try:
                result = future.result()
                function_results.append(result)

                logger.info(
                    "Function improve result received. ticket_id=%s, function_id=%s, improved_count=%s",
                    ticket_id,
                    function_id,
                    result.get("improved_count"),
                )

            except Exception as error:
                errors.append(
                    {
                        "function_id": function_id,
                        "error": str(error),
                    }
                )

                if _is_fail_fast_improve_enabled():
                    logger.exception(
                        "Function improve failed. ticket_id=%s, function_id=%s",
                        ticket_id,
                        function_id,
                    )
                else:
                    logger.warning(
                        "Function improve failed, fallback will be used. "
                        "ticket_id=%s, function_id=%s, error=%s",
                        ticket_id,
                        function_id,
                        _short_error(error),
                    )

                    group = executable_groups[function_id]

                    fallback_result = _build_fallback_improve_result(
                        function_id=function_id,
                        function_item=group["function"],
                        function_testcases=group["testcases"],
                        error=error,
                    )

                    function_results.append(fallback_result)

    if errors:
        error_file = save_raw_response(
            ticket_id,
            "improve_testcases_function_errors",
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        if _is_fail_fast_improve_enabled():
            raise ValueError(
                "One or more main functions failed during parallel improve.\n"
                f"Error details saved to: {error_file}\n"
                f"Errors: {errors}"
            )

        logger.warning(
            "One or more function improves failed, but fallback was used. "
            "ticket_id=%s, error_file=%s",
            ticket_id,
            error_file,
        )

    function_results = _deduplicate_function_results(
        function_results
    )

    function_results.sort(
        key=lambda item: item["function_id"]
    )

    merged_testcases = []

    for result in function_results:
        merged_testcases.extend(
            result["improved_testcases"]
        )

    merged_testcases = _renumber_master_testcases(
        merged_testcases
    )

    _validate_no_duplicate_testcase_ids(
        merged_testcases
    )

    validate_merged_testcases(
        original_testcases=original_testcases,
        merged_testcases=merged_testcases,
    )

    improved_file = save_improved_testcases(
        ticket_id,
        merged_testcases,
        version=improve_version,
    )

    master_file = save_testcases(
        ticket_id,
        merged_testcases,
    )

    manifest = {
        "generation_mode": "FUNCTION_BASED_PARALLEL_IMPROVE_COMPACT_PATCH",
        "parallel_workers": worker_count,
        "function_count": len(function_results),
        "original_count": len(original_testcases),
        "improved_count": len(merged_testcases),
        "improved_file": improved_file,
        "master_file": master_file,
        "functions": [
            {
                "function_id": result["function_id"],
                "function_name": result["function_name"],
                "original_count": result["original_count"],
                "patch_count": result["patch_count"],
                "improved_count": result["improved_count"],
                "file": result.get("file", ""),
                "raw_file": result.get("raw_file", ""),
                "fallback_used": result.get("fallback_used", False),
                "fallback_reason": result.get("fallback_reason", ""),
                "skipped": result.get("skipped", False),
                "skip_reason": result.get("skip_reason", ""),
            }
            for result in function_results
        ],
        "errors": errors,
    }

    manifest_file = save_function_improve_manifest(
        ticket_id,
        manifest,
    )

    save_raw_response(
        ticket_id,
        "improve_testcases_function_manifest",
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    logger.info(
        "Function-based test case improvement completed. ticket_id=%s, original_count=%s, improved_count=%s, improved_file=%s, master_file=%s, manifest_file=%s",
        ticket_id,
        len(original_testcases),
        len(merged_testcases),
        improved_file,
        master_file,
        manifest_file,
    )

    return {
        "improved_testcases": merged_testcases,
        "testcases": merged_testcases,
        "function_improve_results": function_results,
        "function_improve_manifest_file": manifest_file,
    }


def run_improve_testcases(state):
    return improve_testcases(state)
