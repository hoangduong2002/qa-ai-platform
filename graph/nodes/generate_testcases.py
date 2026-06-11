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


def repair_json_with_llm(
    ticket_id: str,
    function_id: str,
    malformed_json_text: str,
    original_error: Exception,
):
    """
    Repair malformed JSON returned by function-level test case generation.

    Common issues:
    - notes after JSON values, e.g. "password": "abc" (example only)
    - unescaped double quotes inside strings
    - raw newlines inside strings
    - missing quotes
    - trailing commas
    """

    logger.warning(
        "Attempting to repair malformed testcases JSON. "
        "ticket_id=%s, function_id=%s, error=%s",
        ticket_id,
        function_id,
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
- Preserve all valid test cases and fields as much as possible.
- Fix missing quotes.
- Fix unescaped double quotes inside JSON strings.
- Fix unescaped newlines inside strings.
- Fix trailing commas.
- Fix invalid comments or notes after JSON values.
- Example malformed: "password": "abc" (example only)
- Example fixed: "password": "abc", "password_note": "example only"
- Example malformed: "password": "A1a!" (example – actual must be exactly 128 chars)
- Example fixed: "password": "A1a!", "password_note": "actual must be exactly 128 chars"
- Do not invent new test cases.
- Do not remove valid test cases.
- Every string must start and end on the same line.
- Every object inside arrays must be closed with }} before the next comma or closing ].

Original parse error:
{original_error}

Malformed JSON:
{malformed_json_text}
"""

    llm = get_llm()

    response = llm.invoke(
        repair_prompt,
        ticket_id=ticket_id,
        node_name=f"generate_testcases_{function_id}_json_repair",
    )

    repaired_raw_file = save_raw_response(
        ticket_id,
        f"generate_testcases_{function_id}_repaired_raw",
        response.content,
    )

    logger.info(
        "Repaired testcases JSON response saved. "
        "ticket_id=%s, function_id=%s, file=%s",
        ticket_id,
        function_id,
        repaired_raw_file,
    )

    return parse_json(response.content)


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


def _build_scenario_index(scenarios: list) -> dict:
    """
    Build a mapping from scenario_id to all metadata that test cases can derive.

    This allows LLM test case output to stay compact:
    - no function_id
    - no sub_function_id
    - no test_area_id
    - no related_requirement_ids
    - no traceability
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


def _normalize_compact_testcase(
    testcase: dict,
    scenario_index: dict,
) -> dict:
    """
    Normalize compact LLM output into the existing internal schema.

    LLM compact output example:
    {
      "testcase_id": "TC001",
      "scenario_id": "SC001",
      "title": "...",
      "type": "Positive",
      "priority": "High",
      "preconditions": [],
      "steps": [],
      "expected": []
    }

    Internal compatibility schema:
    {
      "testcase_id": "TC001",
      "scenario_id": "SC001",
      "function_id": "FUNC001",
      "sub_function_id": "SUB001",
      "test_area_id": "CAT001",
      "title": "...",
      "type": "Positive",
      "priority": "High",
      "preconditions": [],
      "test_steps": [],
      "expected_results": [],
      "related_requirement_ids": ["FR001"],
      "traceability": "FR001"
    }
    """

    if not isinstance(testcase, dict):
        return {}

    scenario_id = testcase.get("scenario_id", "")
    scenario_info = scenario_index.get(scenario_id, {})

    related_requirement_ids = (
        testcase.get("related_requirement_ids")
        or testcase.get("requirement_ids")
        or scenario_info.get("related_requirement_ids")
        or []
    )

    related_requirement_ids = _normalize_requirement_ids(
        related_requirement_ids
    )

    test_steps = (
        testcase.get("steps")
        or testcase.get("test_steps")
        or []
    )

    expected_results = (
        testcase.get("expected")
        or testcase.get("expected_results")
        or []
    )

    return {
        "testcase_id": testcase.get("testcase_id", ""),
        "scenario_id": scenario_id,
        "function_id": (
            testcase.get("function_id")
            or scenario_info.get("function_id", "")
        ),
        "sub_function_id": (
            testcase.get("sub_function_id")
            or scenario_info.get("sub_function_id", "")
        ),
        "test_area_id": (
            testcase.get("test_area_id")
            or scenario_info.get("test_area_id", "")
        ),
        "title": testcase.get("title", ""),
        "type": testcase.get("type", ""),
        "technique": _normalize_technique(
            testcase.get("technique"),
            testcase.get("type", ""),
        ),
        "priority": testcase.get("priority", ""),
        "preconditions": _normalize_list_field(
            testcase.get("preconditions", [])
        ),
        "test_steps": _normalize_list_field(test_steps),
        "expected_results": _normalize_list_field(expected_results),
        "related_requirement_ids": related_requirement_ids,
        "traceability": ", ".join(related_requirement_ids),
    }


def _normalize_compact_testcases(
    testcases: list,
    scenarios: list,
) -> list:
    scenario_index = _build_scenario_index(scenarios)

    normalized = []

    for testcase in testcases:
        normalized_item = _normalize_compact_testcase(
            testcase=testcase,
            scenario_index=scenario_index,
        )

        if normalized_item:
            normalized.append(normalized_item)

    return normalized


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

        if not item.get("function_id"):
            invalid_items.append(item)
            continue

        if not item.get("test_area_id"):
            invalid_items.append(item)
            continue

        if not item.get("related_requirement_ids"):
            invalid_items.append(item)
            continue

        if not item.get("test_steps"):
            invalid_items.append(item)
            continue

        if not item.get("expected_results"):
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


def _get_batch_size() -> int:
    configured_value = os.getenv("TESTCASE_SCENARIO_BATCH_SIZE", "5")

    try:
        batch_size = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid TESTCASE_SCENARIO_BATCH_SIZE value: %s. Falling back to 5.",
            configured_value,
        )
        batch_size = 5

    return max(batch_size, 1)


def _get_batch_parallel_workers(batch_count: int) -> int:
    configured_value = os.getenv("TESTCASE_BATCH_PARALLEL_WORKERS", "2")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid TESTCASE_BATCH_PARALLEL_WORKERS value: %s. Falling back to 2.",
            configured_value,
        )
        configured_workers = 2

    configured_workers = max(configured_workers, 1)

    return min(batch_count, configured_workers)


def _chunk_list(items: list, chunk_size: int) -> list[list]:
    return [
        items[index:index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _renumber_function_testcases(
    testcases: list,
    function_id: str,
) -> list:
    renumbered = []

    for index, testcase in enumerate(testcases, start=1):
        item = dict(testcase)
        item["testcase_id"] = f"{function_id}_TC{index:03d}"
        item["function_id"] = item.get("function_id") or function_id
        renumbered.append(item)

    return renumbered


def _generate_testcases_for_scenario_batch(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    function_id: str,
    function_item: dict,
    batch_index: int,
    function_scenarios_batch: list,
) -> dict:
    logger.info(
        "Generating test cases for function batch. "
        "ticket_id=%s, function_id=%s, batch_index=%s, scenario_count=%s",
        ticket_id,
        function_id,
        batch_index,
        len(function_scenarios_batch),
    )

    llm = get_llm()

    final_prompt = _build_function_prompt(
        requirement_summary=requirement_summary,
        test_scope=test_scope,
        function_item=function_item,
        function_scenarios=function_scenarios_batch,
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"generate_testcases_{function_id}_batch_{batch_index}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"generate_testcases_{function_id}_batch_{batch_index}_raw",
        response.content,
    )

    try:
        try:
            parsed = parse_json(response.content)
        except Exception as parse_error:
            parsed = repair_json_with_llm(
                ticket_id=ticket_id,
                function_id=f"{function_id}_batch_{batch_index}",
                malformed_json_text=response.content,
                original_error=parse_error,
            )

        raw_testcases = normalize_testcases(parsed)

        testcases = _normalize_compact_testcases(
            testcases=raw_testcases,
            scenarios=function_scenarios_batch,
        )

        expected_scenario_ids = {
            scenario.get("scenario_id")
            for scenario in function_scenarios_batch
            if isinstance(scenario, dict) and scenario.get("scenario_id")
        }

        _validate_testcases_for_function(
            testcases=testcases,
            function_id=function_id,
            expected_scenario_ids=expected_scenario_ids,
        )

    except Exception as error:
        error_file = save_raw_response(
            ticket_id,
            f"generate_testcases_{function_id}_batch_{batch_index}_parse_error",
            (
                f"Failed to parse or validate test cases for {function_id}, batch {batch_index}.\n\n"
                f"Function:\n"
                f"{json.dumps(function_item, indent=2, ensure_ascii=False)}\n\n"
                f"Scenarios:\n"
                f"{json.dumps(function_scenarios_batch, indent=2, ensure_ascii=False)}\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        raise ValueError(
            f"Failed to generate test cases for {function_id}, batch {batch_index}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    logger.info(
        "Generated test cases for function batch. "
        "ticket_id=%s, function_id=%s, batch_index=%s, testcase_count=%s",
        ticket_id,
        function_id,
        batch_index,
        len(testcases),
    )

    return {
        "function_id": function_id,
        "batch_index": batch_index,
        "scenario_count": len(function_scenarios_batch),
        "testcase_count": len(testcases),
        "testcases": testcases,
        "raw_file": raw_file,
    }


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

    The function is further split into scenario batches to prevent
    oversized LLM responses and malformed JSON.
    """

    logger.info(
        "Generating test cases for function using scenario batches. "
        "ticket_id=%s, function_id=%s, scenario_count=%s",
        ticket_id,
        function_id,
        len(function_scenarios),
    )

    batch_size = _get_batch_size()
    scenario_batches = _chunk_list(
        function_scenarios,
        batch_size,
    )

    batch_worker_count = _get_batch_parallel_workers(
        len(scenario_batches)
    )

    logger.info(
        "Function split into batches. "
        "ticket_id=%s, function_id=%s, batch_count=%s, batch_size=%s, batch_workers=%s",
        ticket_id,
        function_id,
        len(scenario_batches),
        batch_size,
        batch_worker_count,
    )

    batch_results = []
    batch_errors = []

    with ThreadPoolExecutor(max_workers=batch_worker_count) as executor:
        future_map = {}

        for batch_index, scenario_batch in enumerate(
            scenario_batches,
            start=1,
        ):
            future = executor.submit(
                _generate_testcases_for_scenario_batch,
                ticket_id,
                requirement_summary,
                test_scope,
                function_id,
                function_item,
                batch_index,
                scenario_batch,
            )

            future_map[future] = batch_index

        for future in as_completed(future_map):
            batch_index = future_map[future]

            try:
                batch_results.append(future.result())
            except Exception as error:
                logger.exception(
                    "Function batch generation failed. "
                    "ticket_id=%s, function_id=%s, batch_index=%s",
                    ticket_id,
                    function_id,
                    batch_index,
                )

                batch_errors.append(
                    {
                        "function_id": function_id,
                        "batch_index": batch_index,
                        "error": str(error),
                    }
                )

    if batch_errors:
        error_file = save_raw_response(
            ticket_id,
            f"generate_testcases_{function_id}_batch_errors",
            json.dumps(
                batch_errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            f"One or more scenario batches failed for {function_id}.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {batch_errors}"
        )

    batch_results.sort(key=lambda item: item["batch_index"])

    testcases = []

    for batch_result in batch_results:
        testcases.extend(batch_result["testcases"])

    expected_scenario_ids = {
        scenario.get("scenario_id")
        for scenario in function_scenarios
        if isinstance(scenario, dict) and scenario.get("scenario_id")
    }

    generated_scenario_ids = {
        testcase.get("scenario_id")
        for testcase in testcases
        if isinstance(testcase, dict) and testcase.get("scenario_id")
    }

    missing_scenario_ids = expected_scenario_ids - generated_scenario_ids

    if missing_scenario_ids:
        raise ValueError(
            f"Function {function_id} is missing test cases after batch merge "
            f"for scenarios: {sorted(missing_scenario_ids)}"
        )

    testcases = _renumber_function_testcases(
        testcases,
        function_id,
    )

    function_file = save_function_testcases(
        ticket_id=ticket_id,
        function_id=function_id,
        testcases=testcases,
    )

    logger.info(
        "Generated test cases for function. "
        "ticket_id=%s, function_id=%s, scenario_count=%s, testcase_count=%s, file=%s",
        ticket_id,
        function_id,
        len(function_scenarios),
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
        "raw_file": "",
        "batch_count": len(batch_results),
        "batch_size": batch_size,
        "batch_results": batch_results,
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
    metadata = state.get("requirement_context_metadata") or {}

    if metadata:
        print(
            "generate_testcases context_source="
            f"{metadata.get('context_source')}, "
            f"length={metadata.get('context_length')}, "
            f"path={metadata.get('context_path')}"
        )

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
        "Loaded approved structure. "
        "ticket_id=%s, function_count=%s, scenario_count=%s",
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
            "Some scenarios cannot be mapped to a main function. "
            "ticket_id=%s, unmatched_count=%s, file=%s",
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
        "Grouped scenarios by main function. "
        "ticket_id=%s, function_count=%s, executable_function_count=%s, worker_count=%s",
        ticket_id,
        len(groups),
        len(executable_groups),
        worker_count,
    )

    for function_id, group in executable_groups.items():
        logger.info(
            "Function group ready. "
            "ticket_id=%s, function_id=%s, function_name=%s, scenario_count=%s",
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
                    "Function generation completed. "
                    "ticket_id=%s, function_id=%s, testcase_count=%s",
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
            "One or more main functions failed during parallel test case generation. "
            "ticket_id=%s, error_count=%s, file=%s",
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
        "generation_mode": "FUNCTION_BASED_PARALLEL_COMPACT_OUTPUT",
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
                "batch_count": result.get("batch_count", 0),
                "batch_size": result.get("batch_size", 0),
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
        "Function-based test case generation completed. "
        "ticket_id=%s, function_count=%s, testcase_count=%s, master_file=%s, manifest_file=%s",
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
