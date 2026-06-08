import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_raw_response
from app.utils.function_review_store import (
    save_function_coverage_review,
    save_master_coverage_review,
    save_function_coverage_manifest,
)
from app.services.coverage_score_service import (
    build_deterministic_coverage_review,
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
            value = str(value)

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


def _scenario_matches_function_by_requirement(
    scenario: dict,
    function_item: dict,
) -> bool:
    scenario_requirement_ids = set(_get_related_requirement_ids(scenario))
    function_requirement_ids = set(_get_related_requirement_ids(function_item))

    if not scenario_requirement_ids or not function_requirement_ids:
        return False

    return bool(
        scenario_requirement_ids.intersection(function_requirement_ids)
    )


def _testcase_matches_function_by_requirement(
    testcase: dict,
    function_item: dict,
) -> bool:
    testcase_requirement_ids = set(_get_related_requirement_ids(testcase))
    function_requirement_ids = set(_get_related_requirement_ids(function_item))

    if not testcase_requirement_ids or not function_requirement_ids:
        return False

    return bool(
        testcase_requirement_ids.intersection(function_requirement_ids)
    )


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


def _normalize_review(data: Any) -> dict:
    if isinstance(data, dict):
        return data

    raise ValueError(
        "Invalid coverage review JSON format. Expected JSON object."
    )


def _validate_function_review(
    review: dict,
    function_id: str,
) -> None:
    if not isinstance(review, dict):
        raise ValueError(
            f"Coverage review for {function_id} must be a JSON object."
        )

    if not review.get("function_id"):
        review["function_id"] = function_id

    score = review.get("coverage_score")

    if not isinstance(score, int):
        try:
            review["coverage_score"] = int(score)
        except Exception as error:
            raise ValueError(
                f"Invalid coverage_score for {function_id}: {score}"
            ) from error

    review["coverage_score"] = max(0, min(100, review["coverage_score"]))

    if "approved_by_ai" not in review:
        review["approved_by_ai"] = review["coverage_score"] >= 85

    for key in [
        "covered_scenarios",
        "missing_scenarios",
        "weak_testcases",
        "missing_testcases",
        "traceability_issues",
        "recommendations",
    ]:
        if not isinstance(review.get(key), list):
            review[key] = []


def _to_slim_testcases(testcases: list) -> list:
    slim = []

    for testcase in testcases:
        if not isinstance(testcase, dict):
            continue

        test_steps = testcase.get("test_steps", [])
        expected_results = testcase.get("expected_results", [])

        slim.append(
            {
                "testcase_id": testcase.get("testcase_id", ""),
                "scenario_id": testcase.get("scenario_id", ""),
                "function_id": testcase.get("function_id", ""),
                "sub_function_id": testcase.get("sub_function_id", ""),
                "test_area_id": testcase.get("test_area_id", ""),
                "title": testcase.get("title", ""),
                "type": testcase.get("type", ""),
                "technique": testcase.get("technique", ""),
                "priority": testcase.get("priority", ""),
                "related_requirement_ids": testcase.get(
                    "related_requirement_ids",
                    [],
                ),
                "traceability": testcase.get("traceability", ""),
                "step_count": (
                    len(test_steps)
                    if isinstance(test_steps, list)
                    else 0
                ),
                "expected_result_count": (
                    len(expected_results)
                    if isinstance(expected_results, list)
                    else 0
                ),
            }
        )

    return slim


def _build_function_review_prompt(
    requirement_summary: dict,
    test_scope: dict,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
) -> str:
    prompt = load_prompt("prompts/function_coverage_review.md")

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
                _to_slim_testcases(function_testcases),
                indent=2,
                ensure_ascii=False,
            ),
        )
    )


def _build_deterministic_coverage_review(
    function_id: str,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
) -> dict:
    return build_deterministic_coverage_review(
        function_id=function_id,
        function_name=_get_function_name(function_item),
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
    )


def _should_use_llm_review(deterministic_review: dict) -> bool:
    """
    Use deterministic scoring as the default.

    Only call LLM review when deterministic scoring finds meaningful gaps.
    This keeps token usage low while still allowing AI review for problematic
    functions.
    """

    if not isinstance(deterministic_review, dict):
        return True

    if deterministic_review.get("approved_by_ai"):
        return False

    if deterministic_review.get("coverage_score", 0) >= 90:
        return False

    high_risk_keys = [
        "missing_scenarios",
        "traceability_issues",
    ]

    for key in high_risk_keys:
        if deterministic_review.get(key):
            return True

    weak_testcases = deterministic_review.get("weak_testcases", [])

    if len(weak_testcases) >= 5:
        return True

    return False


def _generate_coverage_review_for_function(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    function_id: str,
    function_item: dict,
    function_scenarios: list,
    function_testcases: list,
) -> dict:
    logger.info(
        "Starting function coverage review. "
        "ticket_id=%s, function_id=%s, scenario_count=%s, testcase_count=%s",
        ticket_id,
        function_id,
        len(function_scenarios),
        len(function_testcases),
    )

    deterministic_review = _build_deterministic_coverage_review(
        function_id=function_id,
        function_item=function_item,
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
    )

    if not _should_use_llm_review(deterministic_review):
        review_file = save_function_coverage_review(
            ticket_id=ticket_id,
            function_id=function_id,
            review=deterministic_review,
        )

        return {
            "function_id": function_id,
            "function_name": deterministic_review["function_name"],
            "coverage_score": deterministic_review.get("coverage_score", 0),
            "approved_by_ai": deterministic_review.get(
                "approved_by_ai",
                False,
            ),
            "scenario_count": len(function_scenarios),
            "testcase_count": len(function_testcases),
            "review": deterministic_review,
            "file": review_file,
            "raw_file": "",
            "review_mode": deterministic_review.get(
                "review_mode",
                "DETERMINISTIC_SCORE",
            ),
        }

    llm = get_llm()

    final_prompt = _build_function_review_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"coverage_review_{function_id}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"coverage_review_{function_id}_raw",
        response.content,
    )

    try:
        parsed = parse_json(response.content)
        review = _normalize_review(parsed)
        _validate_function_review(review, function_id)

    except Exception as error:
        error_file = save_raw_response(
            ticket_id,
            f"coverage_review_{function_id}_parse_error",
            (
                f"Failed to parse or validate coverage review for {function_id}.\n\n"
                f"Function:\n"
                f"{json.dumps(function_item, indent=2, ensure_ascii=False)}\n\n"
                f"Scenarios:\n"
                f"{json.dumps(function_scenarios, indent=2, ensure_ascii=False)}\n\n"
                f"Test Cases:\n"
                f"{json.dumps(function_testcases, indent=2, ensure_ascii=False)}\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        logger.exception(
            "Function coverage review failed. ticket_id=%s, function_id=%s",
            ticket_id,
            function_id,
        )

        raise ValueError(
            f"Failed to generate coverage review for {function_id}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    review["function_id"] = function_id
    review["function_name"] = (
        review.get("function_name")
        or _get_function_name(function_item)
    )
    review["scenario_count"] = len(function_scenarios)
    review["testcase_count"] = len(function_testcases)
    review["review_mode"] = review.get("review_mode") or "LLM_REVIEW"

    # Keep deterministic score breakdown even when LLM review is used.
    if deterministic_review.get("score_breakdown"):
        review["deterministic_score_breakdown"] = deterministic_review.get(
            "score_breakdown"
        )

    review_file = save_function_coverage_review(
        ticket_id=ticket_id,
        function_id=function_id,
        review=review,
    )

    logger.info(
        "Function coverage review completed. "
        "ticket_id=%s, function_id=%s, coverage_score=%s, file=%s",
        ticket_id,
        function_id,
        review.get("coverage_score"),
        review_file,
    )

    return {
        "function_id": function_id,
        "function_name": review["function_name"],
        "coverage_score": review.get("coverage_score", 0),
        "approved_by_ai": review.get("approved_by_ai", False),
        "scenario_count": len(function_scenarios),
        "testcase_count": len(function_testcases),
        "review": review,
        "file": review_file,
        "raw_file": raw_file,
        "review_mode": review.get("review_mode", "LLM_REVIEW"),
    }


def _get_parallel_workers(function_count: int) -> int:
    configured_value = os.getenv("COVERAGE_REVIEW_PARALLEL_WORKERS", "3")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid COVERAGE_REVIEW_PARALLEL_WORKERS value: %s. "
            "Falling back to 3.",
            configured_value,
        )
        configured_workers = 3

    configured_workers = max(configured_workers, 1)
    return min(function_count, configured_workers)


def _merge_function_reviews(
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
            sum(
                result.get("coverage_score", 0)
                for result in function_results
            )
            / len(function_results)
        )
    else:
        average_score = 0

    all_missing_scenarios = []
    all_weak_testcases = []
    all_missing_testcases = []
    all_traceability_issues = []
    all_recommendations = []

    score_breakdowns = []

    for review in function_reviews:
        function_id = review.get("function_id")
        function_name = review.get("function_name")

        score_breakdown = review.get("score_breakdown")

        if score_breakdown:
            score_breakdowns.append(
                {
                    "function_id": function_id,
                    "function_name": function_name,
                    **score_breakdown,
                }
            )

        for item in review.get("missing_scenarios", []):
            if isinstance(item, dict):
                item["function_id"] = item.get("function_id") or function_id
                item["function_name"] = (
                    item.get("function_name")
                    or function_name
                )
            all_missing_scenarios.append(item)

        for item in review.get("weak_testcases", []):
            if isinstance(item, dict):
                item["function_id"] = item.get("function_id") or function_id
                item["function_name"] = (
                    item.get("function_name")
                    or function_name
                )
            all_weak_testcases.append(item)

        for item in review.get("missing_testcases", []):
            if isinstance(item, dict):
                item["function_id"] = item.get("function_id") or function_id
                item["function_name"] = (
                    item.get("function_name")
                    or function_name
                )
            all_missing_testcases.append(item)

        for item in review.get("traceability_issues", []):
            if isinstance(item, dict):
                item["function_id"] = item.get("function_id") or function_id
                item["function_name"] = (
                    item.get("function_name")
                    or function_name
                )
            all_traceability_issues.append(item)

        for item in review.get("recommendations", []):
            if isinstance(item, dict):
                item["function_id"] = item.get("function_id") or function_id
                item["function_name"] = (
                    item.get("function_name")
                    or function_name
                )
            all_recommendations.append(item)

    approved_by_ai = (
        bool(function_results)
        and all(
            result.get("approved_by_ai", False)
            for result in function_results
        )
    )

    master_review = {
        "generation_mode": "FUNCTION_BASED_PARALLEL_COVERAGE_REVIEW",
        "coverage_score": average_score,
        "approved_by_ai": approved_by_ai,
        "summary": (
            f"Function-level coverage review completed for "
            f"{len(function_results)} main functions. "
            f"Average coverage score: {average_score}."
        ),
        "function_count": len(function_results),
        "scenario_count": len(scenarios),
        "testcase_count": len(testcases),
        "parallel_workers": worker_count,
        "function_reviews": function_reviews,
        "score_breakdowns": score_breakdowns,
        "missing_scenarios": all_missing_scenarios,
        "weak_testcases": all_weak_testcases,
        "missing_testcases": all_missing_testcases,
        "traceability_issues": all_traceability_issues,
        "recommendations": all_recommendations,
    }

    master_file = save_master_coverage_review(
        ticket_id,
        master_review,
    )

    manifest = {
        "generation_mode": "FUNCTION_BASED_PARALLEL_COVERAGE_REVIEW",
        "parallel_workers": worker_count,
        "function_count": len(function_results),
        "scenario_count": len(scenarios),
        "testcase_count": len(testcases),
        "coverage_score": average_score,
        "approved_by_ai": approved_by_ai,
        "master_file": master_file,
        "functions": [
            {
                "function_id": result["function_id"],
                "function_name": result["function_name"],
                "coverage_score": result["coverage_score"],
                "approved_by_ai": result["approved_by_ai"],
                "scenario_count": result["scenario_count"],
                "testcase_count": result["testcase_count"],
                "file": result["file"],
                "raw_file": result["raw_file"],
                "review_mode": result.get("review_mode", ""),
            }
            for result in function_results
        ],
    }

    manifest_file = save_function_coverage_manifest(
        ticket_id,
        manifest,
    )

    save_raw_response(
        ticket_id,
        "coverage_review_function_manifest",
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    master_review["coverage_review_file"] = master_file
    master_review["function_coverage_manifest_file"] = manifest_file

    return master_review


def coverage_review(state):
    ticket_id = state["ticket_id"]

    logger.info(
        "Starting function-based coverage review. ticket_id=%s",
        ticket_id,
    )

    approved_structure = state.get("approved_test_case_structure", {})
    scenarios = state.get("scenarios", [])
    testcases = state.get("testcases", [])

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for function-based "
            "coverage review."
        )

    if not scenarios:
        raise ValueError(
            "scenarios is required before coverage review."
        )

    if not testcases:
        raise ValueError(
            "testcases is required before coverage review."
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
        unmatched_scenarios_file = save_raw_response(
            ticket_id,
            "coverage_review_unmatched_scenarios",
            json.dumps(
                unmatched_scenarios,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some scenarios cannot be mapped to a main function during "
            "coverage review.\n"
            f"Unmatched scenarios saved to: {unmatched_scenarios_file}"
        )

    if unmatched_testcases:
        unmatched_testcases_file = save_raw_response(
            ticket_id,
            "coverage_review_unmatched_testcases",
            json.dumps(
                unmatched_testcases,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "Some test cases cannot be mapped to a main function during "
            "coverage review.\n"
            f"Unmatched test cases saved to: {unmatched_testcases_file}"
        )

    executable_groups = {
        function_id: group
        for function_id, group in groups.items()
        if group.get("scenarios") or group.get("testcases")
    }

    if not executable_groups:
        raise ValueError(
            "No scenarios/testcases could be grouped by main function for "
            "coverage review."
        )

    worker_count = _get_parallel_workers(len(executable_groups))

    logger.info(
        "Grouped coverage review items by function. "
        "ticket_id=%s, function_count=%s, worker_count=%s",
        ticket_id,
        len(executable_groups),
        worker_count,
    )

    function_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {}

        for function_id, group in executable_groups.items():
            future = executor.submit(
                _generate_coverage_review_for_function,
                ticket_id,
                state.get("requirement_summary", {}),
                state.get("test_scope", {}),
                function_id,
                group["function"],
                group["scenarios"],
                group["testcases"],
            )

            future_map[future] = function_id

        for future in as_completed(future_map):
            function_id = future_map[future]

            try:
                result = future.result()
                function_results.append(result)

                logger.info(
                    "Function coverage review result received. "
                    "ticket_id=%s, function_id=%s, coverage_score=%s",
                    ticket_id,
                    function_id,
                    result.get("coverage_score"),
                )

            except Exception as error:
                logger.exception(
                    "Function coverage review failed. "
                    "ticket_id=%s, function_id=%s",
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
            "coverage_review_function_errors",
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "One or more main functions failed during parallel coverage "
            "review.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {errors}"
        )

    function_results.sort(key=lambda item: item["function_id"])

    master_review = _merge_function_reviews(
        ticket_id=ticket_id,
        function_results=function_results,
        scenarios=scenarios,
        testcases=testcases,
        worker_count=worker_count,
    )

    logger.info(
        "Function-based coverage review completed. "
        "ticket_id=%s, function_count=%s, coverage_score=%s",
        ticket_id,
        len(function_results),
        master_review.get("coverage_score"),
    )

    return {
        "coverage_review": master_review,
    }


def review_coverage(state):
    return coverage_review(state)


def run_coverage_review(state):
    return coverage_review(state)