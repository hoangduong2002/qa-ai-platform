import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_raw_response
from app.utils.test_structure_store import load_approved_test_case_structure
from app.utils.function_final_review_store import (
    save_function_final_review,
    save_master_final_review,
    save_function_final_review_manifest,
)


logger = logging.getLogger(__name__)


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


def _item_matches_function_by_requirement(
    item: dict,
    function_item: dict,
) -> bool:
    item_requirement_ids = set(_get_related_requirement_ids(item))
    function_requirement_ids = set(_get_related_requirement_ids(function_item))

    if not item_requirement_ids or not function_requirement_ids:
        return False

    return bool(item_requirement_ids.intersection(function_requirement_ids))


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
            if _item_matches_function_by_requirement(
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
            if _item_matches_function_by_requirement(
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


def _normalize_final_review(data: Any) -> dict:
    if isinstance(data, dict):
        return data

    raise ValueError(
        "Invalid final coverage review JSON format. Expected JSON object."
    )


def _validate_function_final_review(
    review: dict,
    function_id: str,
) -> None:
    if not isinstance(review, dict):
        raise ValueError(
            f"Final coverage review for {function_id} must be a JSON object."
        )

    if not review.get("function_id"):
        review["function_id"] = function_id

    score = review.get("final_coverage_score")

    if score is None:
        score = review.get("coverage_score")

    if not isinstance(score, int):
        try:
            score = int(score)
        except Exception as error:
            raise ValueError(
                f"Invalid final_coverage_score for {function_id}: {score}"
            ) from error

    review["final_coverage_score"] = max(0, min(100, score))

    if "approved_by_ai" not in review:
        review["approved_by_ai"] = review["final_coverage_score"] >= 85

    if "ready_for_execution" not in review:
        review["ready_for_execution"] = (
            review["approved_by_ai"]
            and not review.get("remaining_gaps")
            and not review.get("execution_readiness_issues")
        )

    for key in [
        "resolved_issues",
        "remaining_gaps",
        "traceability_issues",
        "execution_readiness_issues",
        "final_recommendations",
    ]:
        if not isinstance(review.get(key), list):
            review[key] = []


def repair_json_with_llm(
    ticket_id: str,
    function_id: str,
    malformed_json_text: str,
    original_error: Exception,
):
    logger.warning(
        "Attempting to repair malformed final coverage JSON. ticket_id=%s, function_id=%s, error=%s",
        ticket_id,
        function_id,
        original_error,
    )

    repair_prompt = f"""
You are a JSON repair tool.

Fix the malformed JSON below.

Rules:
- Return ONLY valid JSON.
- Return a JSON object.
- Do not add explanation.
- Do not use markdown.
- Do not wrap in ```json.
- Preserve all fields and values as much as possible.
- Fix missing quotes.
- Fix unescaped newlines inside strings.
- Fix trailing commas.
- Fix unescaped double quotes inside JSON strings.
- Replace unescaped double quotes inside JSON strings with single quotes.
- Example malformed: "recommendation": "Change to ["BR006", "VAL003"]."
- Example fixed: "recommendation": "Change to ['BR006', 'VAL003']."
- Ensure every object inside arrays is closed with }} before the next comma or closing ].
- Do not invent new review findings.
- Do not remove valid review findings.

Original parse error:
{original_error}

Malformed JSON:
{malformed_json_text}
"""

    llm = get_llm()

    response = llm.invoke(
        repair_prompt,
        ticket_id=ticket_id,
        node_name=f"final_coverage_review_{function_id}_json_repair",
    )

    repaired_raw_file = save_raw_response(
        ticket_id,
        f"final_coverage_review_{function_id}_repaired_raw",
        response.content,
    )

    logger.info(
        "Repaired final coverage JSON response saved. ticket_id=%s, function_id=%s, file=%s",
        ticket_id,
        function_id,
        repaired_raw_file,
    )

    return parse_json(response.content)


def _build_function_final_review_prompt(
    requirement_summary: dict,
    test_scope: dict,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
    function_coverage_review: dict,
) -> str:
    prompt = load_prompt("prompts/function_final_coverage_review.md")

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
    )


def _generate_final_review_for_function(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    function_id: str,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
    function_coverage_review: dict,
) -> dict:
    logger.info(
        "Starting function final coverage review. ticket_id=%s, function_id=%s, scenario_count=%s, testcase_count=%s",
        ticket_id,
        function_id,
        len(function_scenarios),
        len(function_testcases),
    )

    llm = get_llm()

    final_prompt = _build_function_final_review_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
        function_coverage_review=function_coverage_review,
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"final_coverage_review_{function_id}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"final_coverage_review_{function_id}_raw",
        response.content,
    )

    try:
        try:
            parsed = parse_json(response.content)
        except Exception as parse_error:
            parsed = repair_json_with_llm(
                ticket_id=ticket_id,
                function_id=function_id,
                malformed_json_text=response.content,
                original_error=parse_error,
            )

        review = _normalize_final_review(parsed)
        _validate_function_final_review(review, function_id)

    except Exception as error:
        error_file = save_raw_response(
            ticket_id,
            f"final_coverage_review_{function_id}_parse_error",
            (
                f"Failed to parse or validate final coverage review for {function_id}.\n\n"
                f"Function:\n"
                f"{json.dumps(function_item, indent=2, ensure_ascii=False)}\n\n"
                f"Scenarios:\n"
                f"{json.dumps(function_scenarios, indent=2, ensure_ascii=False)}\n\n"
                f"Test Cases:\n"
                f"{json.dumps(function_testcases, indent=2, ensure_ascii=False)}\n\n"
                f"Previous Coverage Review:\n"
                f"{json.dumps(function_coverage_review, indent=2, ensure_ascii=False)}\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        logger.exception(
            "Function final coverage review failed. ticket_id=%s, function_id=%s",
            ticket_id,
            function_id,
        )

        raise ValueError(
            f"Failed to generate final coverage review for {function_id}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    review["function_id"] = function_id
    review["function_name"] = review.get("function_name") or _get_function_name(function_item)
    review["scenario_count"] = len(function_scenarios)
    review["testcase_count"] = len(function_testcases)

    review_file = save_function_final_review(
        ticket_id=ticket_id,
        function_id=function_id,
        review=review,
    )

    logger.info(
        "Function final coverage review completed. ticket_id=%s, function_id=%s, score=%s, ready=%s, file=%s",
        ticket_id,
        function_id,
        review.get("final_coverage_score"),
        review.get("ready_for_execution"),
        review_file,
    )

    return {
        "function_id": function_id,
        "function_name": review["function_name"],
        "final_coverage_score": review.get("final_coverage_score", 0),
        "approved_by_ai": review.get("approved_by_ai", False),
        "ready_for_execution": review.get("ready_for_execution", False),
        "scenario_count": len(function_scenarios),
        "testcase_count": len(function_testcases),
        "review": review,
        "file": review_file,
        "raw_file": raw_file,
    }


def _get_parallel_workers(function_count: int) -> int:
    configured_value = os.getenv("FINAL_REVIEW_PARALLEL_WORKERS", "3")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid FINAL_REVIEW_PARALLEL_WORKERS value: %s. Falling back to 3.",
            configured_value,
        )
        configured_workers = 3

    configured_workers = max(configured_workers, 1)
    return min(function_count, configured_workers)


def _merge_function_final_reviews(
    ticket_id: str,
    function_results: list[dict],
    scenarios: list,
    testcases: list,
    worker_count: int,
) -> dict:
    function_reviews = [
        result["review"]
        for result in function_results
    ]

    if function_results:
        average_score = round(
            sum(result.get("final_coverage_score", 0) for result in function_results)
            / len(function_results)
        )
    else:
        average_score = 0

    all_resolved_issues = []
    all_remaining_gaps = []
    all_traceability_issues = []
    all_execution_readiness_issues = []
    all_final_recommendations = []

    for review in function_reviews:
        function_id = review.get("function_id")
        function_name = review.get("function_name")

        for key, target in [
            ("resolved_issues", all_resolved_issues),
            ("remaining_gaps", all_remaining_gaps),
            ("traceability_issues", all_traceability_issues),
            ("execution_readiness_issues", all_execution_readiness_issues),
            ("final_recommendations", all_final_recommendations),
        ]:
            for item in review.get(key, []):
                if isinstance(item, dict):
                    item["function_id"] = item.get("function_id") or function_id
                    item["function_name"] = item.get("function_name") or function_name
                target.append(item)

    approved_by_ai = (
        bool(function_results)
        and all(result.get("approved_by_ai", False) for result in function_results)
    )

    ready_for_execution = (
        bool(function_results)
        and all(result.get("ready_for_execution", False) for result in function_results)
        and not all_remaining_gaps
        and not all_execution_readiness_issues
    )

    master_review = {
        "generation_mode": "FUNCTION_BASED_PARALLEL_FINAL_COVERAGE_REVIEW",
        "final_coverage_score": average_score,
        "coverage_score": average_score,
        "approved_by_ai": approved_by_ai,
        "ready_for_execution": ready_for_execution,
        "summary": (
            f"Function-level final coverage review completed for {len(function_results)} "
            f"main functions. Average final coverage score: {average_score}."
        ),
        "function_count": len(function_results),
        "scenario_count": len(scenarios),
        "testcase_count": len(testcases),
        "parallel_workers": worker_count,
        "function_reviews": function_reviews,
        "resolved_issues": all_resolved_issues,
        "remaining_gaps": all_remaining_gaps,
        "traceability_issues": all_traceability_issues,
        "execution_readiness_issues": all_execution_readiness_issues,
        "final_recommendations": all_final_recommendations,
    }

    master_file = save_master_final_review(
        ticket_id,
        master_review,
    )

    manifest = {
        "generation_mode": "FUNCTION_BASED_PARALLEL_FINAL_COVERAGE_REVIEW",
        "parallel_workers": worker_count,
        "function_count": len(function_results),
        "scenario_count": len(scenarios),
        "testcase_count": len(testcases),
        "final_coverage_score": average_score,
        "approved_by_ai": approved_by_ai,
        "ready_for_execution": ready_for_execution,
        "master_file": master_file,
        "functions": [
            {
                "function_id": result["function_id"],
                "function_name": result["function_name"],
                "final_coverage_score": result["final_coverage_score"],
                "approved_by_ai": result["approved_by_ai"],
                "ready_for_execution": result["ready_for_execution"],
                "scenario_count": result["scenario_count"],
                "testcase_count": result["testcase_count"],
                "file": result["file"],
                "raw_file": result["raw_file"],
            }
            for result in function_results
        ],
    }

    manifest_file = save_function_final_review_manifest(
        ticket_id,
        manifest,
    )

    save_raw_response(
        ticket_id,
        "final_coverage_review_function_manifest",
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    master_review["final_coverage_review_file"] = master_file
    master_review["function_final_review_manifest_file"] = manifest_file

    return master_review


def final_coverage_review(state):
    ticket_id = state["ticket_id"]

    logger.info(
        "Starting function-based final coverage review. ticket_id=%s",
        ticket_id,
    )

    approved_structure = (
        state.get("approved_test_case_structure")
        or load_approved_test_case_structure(ticket_id)
    )

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for function-based final coverage review."
        )

    scenarios = state.get("scenarios", [])

    testcases = (
        state.get("improved_testcases")
        or state.get("testcases", [])
    )

    coverage_review = state.get("coverage_review", {})

    if not scenarios:
        raise ValueError(
            "scenarios is required before final coverage review."
        )

    if not testcases:
        raise ValueError(
            "testcases or improved_testcases is required before final coverage review."
        )

    functions = _extract_functions(approved_structure)

    if not functions:
        raise ValueError(
            "No main functions found in approved_test_case_structure. "
            "Expected key: main_functions or functions."
        )

    groups, unmatched_scenarios, unmatched_testcases = _group_items_by_function(
        functions=functions,
        scenarios=scenarios,
        testcases=testcases,
    )

    if unmatched_scenarios:
        unmatched_file = save_raw_response(
            ticket_id,
            "final_coverage_review_unmatched_scenarios",
            json.dumps(
                unmatched_scenarios,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some scenarios cannot be mapped to a main function during final coverage review.\n"
            f"Unmatched scenarios saved to: {unmatched_file}"
        )

    if unmatched_testcases:
        unmatched_file = save_raw_response(
            ticket_id,
            "final_coverage_review_unmatched_testcases",
            json.dumps(
                unmatched_testcases,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some test cases cannot be mapped to a main function during final coverage review.\n"
            f"Unmatched test cases saved to: {unmatched_file}"
        )

    executable_groups = {
        function_id: group
        for function_id, group in groups.items()
        if group.get("scenarios") or group.get("testcases")
    }

    if not executable_groups:
        raise ValueError(
            "No scenarios/testcases could be grouped by main function for final coverage review."
        )

    worker_count = _get_parallel_workers(len(executable_groups))

    logger.info(
        "Grouped final review items by function. ticket_id=%s, function_count=%s, worker_count=%s",
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
                _generate_final_review_for_function,
                ticket_id,
                state.get("requirement_summary", {}),
                state.get("test_scope", {}),
                function_id,
                group["function"],
                group["scenarios"],
                group["testcases"],
                function_coverage_review,
            )

            future_map[future] = function_id

        for future in as_completed(future_map):
            function_id = future_map[future]

            try:
                result = future.result()
                function_results.append(result)

                logger.info(
                    "Function final review result received. ticket_id=%s, function_id=%s, score=%s",
                    ticket_id,
                    function_id,
                    result.get("final_coverage_score"),
                )

            except Exception as error:
                logger.exception(
                    "Function final coverage review failed. ticket_id=%s, function_id=%s",
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
            "final_coverage_review_function_errors",
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "One or more main functions failed during parallel final coverage review.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {errors}"
        )

    function_results.sort(key=lambda item: item["function_id"])

    master_review = _merge_function_final_reviews(
        ticket_id=ticket_id,
        function_results=function_results,
        scenarios=scenarios,
        testcases=testcases,
        worker_count=worker_count,
    )

    logger.info(
        "Function-based final coverage review completed. ticket_id=%s, function_count=%s, score=%s, ready=%s",
        ticket_id,
        len(function_results),
        master_review.get("final_coverage_score"),
        master_review.get("ready_for_execution"),
    )

    return {
        "final_coverage_review": master_review,
    }


# Compatibility aliases.
# Keep these in case your graph imports the node function with another name.
def final_review_coverage(state):
    return final_coverage_review(state)


def review_final_coverage(state):
    return final_coverage_review(state)


def run_final_coverage_review(state):
    return final_coverage_review(state)