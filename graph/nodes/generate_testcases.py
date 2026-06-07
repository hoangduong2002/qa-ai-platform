import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_testcases, save_raw_response
from app.utils.function_testcase_store import (
    save_function_testcases,
    save_function_generation_manifest,
)


logger = logging.getLogger(__name__)


def normalize_testcases(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["testcases", "test_cases", "testCases"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(
        "Invalid testcases JSON format. "
        "Expected list or object with testcases/test_cases/testCases key."
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
    return (
        function_item.get("function_id")
        or function_item.get("main_function_id")
        or function_item.get("id")
        or ""
    )


def _get_function_name(function_item: dict) -> str:
    return (
        function_item.get("name")
        or function_item.get("title")
        or function_item.get("function_name")
        or ""
    )


def _get_scenario_function_id(scenario: dict) -> str:
    return (
        scenario.get("function_id")
        or scenario.get("main_function_id")
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


def _group_scenarios_by_function(
    scenarios: list,
    functions: list[dict],
) -> tuple[dict[str, dict], list[dict]]:
    """
    Returns:
    {
      "FUNC001": {
        "function": {...},
        "scenarios": [...]
      }
    },
    unmatched_scenarios
    """

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
        }

    unmatched_scenarios = []

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            unmatched_scenarios.append(scenario)
            continue

        scenario_function_id = _get_scenario_function_id(scenario)

        if scenario_function_id and scenario_function_id in groups:
            groups[scenario_function_id]["scenarios"].append(scenario)
            continue

        matched_function_id = None

        for function_id, function_item in function_by_id.items():
            if _scenario_matches_function_by_requirement(
                scenario,
                function_item,
            ):
                matched_function_id = function_id
                break

        if matched_function_id:
            scenario["function_id"] = matched_function_id
            groups[matched_function_id]["scenarios"].append(scenario)
        else:
            unmatched_scenarios.append(scenario)

    return groups, unmatched_scenarios


def _validate_testcases_for_function(
    testcases: list,
    function_id: str,
    expected_scenario_ids: set[str],
) -> None:
    if not testcases:
        raise ValueError(
            f"No test cases generated for function {function_id}."
        )

    invalid_items = []
    generated_scenario_ids = set()

    for item in testcases:
        if not isinstance(item, dict):
            invalid_items.append(item)
            continue

        if not item.get("testcase_id"):
            invalid_items.append(item)
            continue

        if not item.get("scenario_id"):
            invalid_items.append(item)
            continue

        if not item.get("related_requirement_ids"):
            invalid_items.append(item)
            continue

        generated_scenario_ids.add(item.get("scenario_id"))

        item["function_id"] = item.get("function_id") or function_id

        if not item.get("traceability"):
            item["traceability"] = ", ".join(
                _get_related_requirement_ids(item)
            )

    if invalid_items:
        raise ValueError(
            f"Invalid testcase schema for function {function_id}. "
            f"First invalid item: {invalid_items[0]}"
        )

    missing_scenario_ids = expected_scenario_ids - generated_scenario_ids

    if missing_scenario_ids:
        raise ValueError(
            f"Function {function_id} is missing test cases for scenarios: "
            f"{sorted(missing_scenario_ids)}"
        )


def _renumber_testcases(testcases: list) -> list:
    renumbered = []

    for index, testcase in enumerate(testcases, start=1):
        testcase = dict(testcase)
        testcase["testcase_id"] = f"TC{index:03d}"
        renumbered.append(testcase)

    return renumbered


def _build_function_prompt(
    requirement_summary: dict,
    test_scope: dict,
    function_item: dict,
    function_scenarios: list,
) -> str:
    prompt = load_prompt("prompts/generate_function_testcases.md")

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
    )


def _generate_testcases_for_function(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    function_id: str,
    function_item: dict,
    function_scenarios: list,
) -> dict:
    """
    Generate test cases for one main function.

    This function is designed to be executed in parallel.
    It creates its own LLM instance to avoid sharing client state across threads.
    """

    logger.info(
        "Generating test cases for function. ticket_id=%s, function_id=%s, scenario_count=%s",
        ticket_id,
        function_id,
        len(function_scenarios),
    )

    llm = get_llm()

    final_prompt = _build_function_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=function_scenarios,
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"generate_testcases_{function_id}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"generate_testcases_{function_id}_raw",
        response.content,
    )

    try:
        parsed = parse_json(response.content)
        testcases = normalize_testcases(parsed)

        expected_scenario_ids = {
            scenario.get("scenario_id")
            for scenario in function_scenarios
            if isinstance(scenario, dict) and scenario.get("scenario_id")
        }

        _validate_testcases_for_function(
            testcases=testcases,
            function_id=function_id,
            expected_scenario_ids=expected_scenario_ids,
        )

    except Exception as error:
        logger.exception(
            "Failed to generate test cases for function. ticket_id=%s, function_id=%s",
            ticket_id,
            function_id,
        )

        error_file = save_raw_response(
            ticket_id,
            f"generate_testcases_{function_id}_parse_error",
            (
                f"Failed to parse or validate test cases for {function_id}.\n\n"
                f"Function:\n"
                f"{json.dumps(function_item, indent=2, ensure_ascii=False)}\n\n"
                f"Scenarios:\n"
                f"{json.dumps(function_scenarios, indent=2, ensure_ascii=False)}\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        raise ValueError(
            f"Failed to generate test cases for {function_id}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    function_file = save_function_testcases(
        ticket_id=ticket_id,
        function_id=function_id,
        testcases=testcases,
    )

    logger.info(
        "Generated test cases for function. ticket_id=%s, function_id=%s, testcase_count=%s, file=%s",
        ticket_id,
        function_id,
        len(testcases),
        function_file,
    )

    return {
        "function_id": function_id,
        "function_name": _get_function_name(function_item),
        "scenario_count": len(function_scenarios),
        "testcase_count": len(testcases),
        "testcases": testcases,
        "file": function_file,
        "raw_file": raw_file,
    }


def _get_parallel_workers(function_count: int) -> int:
    configured_value = os.getenv("TESTCASE_PARALLEL_WORKERS", "3")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid TESTCASE_PARALLEL_WORKERS value: %s. Falling back to 3.",
            configured_value,
        )
        configured_workers = 3

    configured_workers = max(configured_workers, 1)

    return min(function_count, configured_workers)


def generate_testcases(state):
    ticket_id = state["ticket_id"]

    logger.info(
        "Starting function-based test case generation. ticket_id=%s",
        ticket_id,
    )

    approved_structure = state.get("approved_test_case_structure", {})
    scenarios = state.get("scenarios", [])

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for structured "
            "function-based test case generation."
        )

    if not scenarios:
        raise ValueError(
            "scenarios is required before generating test cases."
        )

    functions = _extract_functions(approved_structure)

    logger.info(
        "Loaded approved structure. ticket_id=%s, function_count=%s, scenario_count=%s",
        ticket_id,
        len(functions),
        len(scenarios),
    )

    if not functions:
        raise ValueError(
            "No main functions found in approved_test_case_structure. "
            "Expected key: main_functions or functions."
        )

    groups, unmatched_scenarios = _group_scenarios_by_function(
        scenarios=scenarios,
        functions=functions,
    )

    executable_groups = {
        function_id: group
        for function_id, group in groups.items()
        if group.get("scenarios")
    }

    if unmatched_scenarios:
        unmatched_file = save_raw_response(
            ticket_id,
            "generate_testcases_unmatched_scenarios",
            json.dumps(
                unmatched_scenarios,
                indent=2,
                ensure_ascii=False,
            ),
        )

        logger.error(
            "Some scenarios cannot be mapped to a main function. ticket_id=%s, unmatched_count=%s, file=%s",
            ticket_id,
            len(unmatched_scenarios),
            unmatched_file,
        )

        raise ValueError(
            "Some scenarios cannot be mapped to a main function. "
            "Please fix scenario generation or structure traceability first.\n"
            f"Unmatched scenarios saved to: {unmatched_file}"
        )

    if not executable_groups:
        raise ValueError(
            "No scenarios could be grouped by main function."
        )

    worker_count = _get_parallel_workers(len(executable_groups))

    logger.info(
        "Grouped scenarios by main function. ticket_id=%s, function_count=%s, executable_function_count=%s, worker_count=%s",
        ticket_id,
        len(groups),
        len(executable_groups),
        worker_count,
    )

    for function_id, group in executable_groups.items():
        logger.info(
            "Function group ready. ticket_id=%s, function_id=%s, function_name=%s, scenario_count=%s",
            ticket_id,
            function_id,
            _get_function_name(group["function"]),
            len(group["scenarios"]),
        )

    function_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {}

        for function_id, group in executable_groups.items():
            future = executor.submit(
                _generate_testcases_for_function,
                ticket_id,
                state.get("requirement_summary", {}),
                state.get("test_scope", {}),
                function_id,
                group["function"],
                group["scenarios"],
            )

            future_map[future] = function_id

        for future in as_completed(future_map):
            function_id = future_map[future]

            try:
                result = future.result()
                function_results.append(result)

                logger.info(
                    "Function generation completed. ticket_id=%s, function_id=%s, testcase_count=%s",
                    ticket_id,
                    function_id,
                    result.get("testcase_count"),
                )

            except Exception as error:
                logger.exception(
                    "Function generation failed. ticket_id=%s, function_id=%s",
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
            "generate_testcases_function_errors",
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        logger.error(
            "One or more main functions failed during parallel test case generation. ticket_id=%s, error_count=%s, file=%s",
            ticket_id,
            len(errors),
            error_file,
        )

        raise ValueError(
            "One or more main functions failed during parallel test case "
            "generation.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {errors}"
        )

    function_results.sort(key=lambda item: item["function_id"])

    merged_testcases = []

    for result in function_results:
        merged_testcases.extend(result["testcases"])

    merged_testcases = _renumber_testcases(merged_testcases)

    master_file = save_testcases(
        ticket_id,
        merged_testcases,
    )

    manifest = {
        "generation_mode": "FUNCTION_BASED_PARALLEL",
        "parallel_workers": worker_count,
        "function_count": len(function_results),
        "scenario_count": len(scenarios),
        "testcase_count": len(merged_testcases),
        "master_file": master_file,
        "functions": [
            {
                "function_id": result["function_id"],
                "function_name": result["function_name"],
                "scenario_count": result["scenario_count"],
                "testcase_count": result["testcase_count"],
                "file": result["file"],
                "raw_file": result["raw_file"],
            }
            for result in function_results
        ],
    }

    manifest_file = save_function_generation_manifest(
        ticket_id,
        manifest,
    )

    save_raw_response(
        ticket_id,
        "generate_testcases_function_manifest",
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    logger.info(
        "Function-based test case generation completed. ticket_id=%s, function_count=%s, testcase_count=%s, master_file=%s, manifest_file=%s",
        ticket_id,
        len(function_results),
        len(merged_testcases),
        master_file,
        manifest_file,
    )

    return {
        "testcases": merged_testcases,
        "function_testcase_results": function_results,
        "function_generation_manifest_file": manifest_file,
    }