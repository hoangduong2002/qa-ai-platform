import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_service import get_llm
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
            continue

        clean_value = value.strip()

        if not clean_value:
            continue

        if clean_value not in seen:
            seen.add(clean_value)
            result.append(clean_value)

    return result


def _get_related_requirement_ids(item: dict) -> list[str]:
    if not isinstance(item, dict):
        return []

    return _unique_ids(
        _as_list(item.get("related_requirement_ids"))
        + _as_list(item.get("requirement_ids"))
        + _as_list(item.get("related_requirements"))
    )


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

    if not item.get("title"):
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


def _normalize_patch_testcase(
    testcase: dict,
    next_id_number: int,
) -> tuple[dict, int]:
    item = dict(testcase)

    if not item.get("testcase_id"):
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
            merged_item.update(patch_item)

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
):
    """
    Ask LLM to repair malformed JSON output once.

    This is used only as a fallback when parse_json() fails.
    The repaired response is still parsed and validated by the normal pipeline.
    """

    logger.warning(
        "Attempting to repair malformed improve JSON. ticket_id=%s, error=%s",
        ticket_id,
        original_error,
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

    llm = get_llm()

    response = llm.invoke(
        repair_prompt,
        ticket_id=ticket_id,
        node_name="improve_testcases_json_repair",
    )

    repaired_raw_file = save_raw_response(
        ticket_id,
        "improve_testcases_repaired_raw",
        response.content,
    )

    logger.info(
        "Repaired improve JSON response saved. ticket_id=%s, file=%s",
        ticket_id,
        repaired_raw_file,
    )

    return parse_json(response.content)


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
) -> dict:
    logger.info(
        "Starting function-level improve. ticket_id=%s, function_id=%s, testcase_count=%s",
        ticket_id,
        function_id,
        len(function_testcases),
    )

    llm = get_llm()

    final_prompt = _build_function_improve_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
        function_coverage_review=function_coverage_review,
        review_comments=review_comments,
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"improve_testcases_{function_id}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"improve_testcases_{function_id}_raw",
        response.content,
    )

    try:
        try:
            parsed = parse_json(response.content)
        except Exception as parse_error:
            parsed = repair_json_with_llm(
                ticket_id=ticket_id,
                malformed_json_text=response.content,
                original_error=parse_error,
            )

        patch_testcases = normalize_testcases(parsed)

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

        logger.exception(
            "Function-level improve failed. ticket_id=%s, function_id=%s",
            ticket_id,
            function_id,
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


def improve_testcases(state):
    ticket_id = state["ticket_id"]

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
                state.get("review_comments", []),
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
                logger.exception(
                    "Function improve failed. ticket_id=%s, function_id=%s",
                    ticket_id,
                    function_id,
                )

                errors.append(
                    {
                        "function_id": function_id,
                        "error": str(error),
                    }
                )

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

        raise ValueError(
            "One or more main functions failed during parallel improve.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {errors}"
        )

    function_results.sort(key=lambda item: item["function_id"])

    merged_testcases = []

    for result in function_results:
        merged_testcases.extend(result["improved_testcases"])

    merged_testcases = _renumber_master_testcases(merged_testcases)

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
        "generation_mode": "FUNCTION_BASED_PARALLEL_IMPROVE",
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
                "file": result["file"],
                "raw_file": result["raw_file"],
            }
            for result in function_results
        ],
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


# Compatibility alias, in case your graph imports a different function name.
def run_improve_testcases(state):
    return improve_testcases(state)