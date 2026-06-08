import json
import logging
from typing import Any
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_scenarios, save_raw_response


logger = logging.getLogger(__name__)


def normalize_scenarios(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["scenarios", "test_scenarios", "testScenarios"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(
        "Invalid scenarios JSON format. "
        "Expected list or object with scenarios/test_scenarios/testScenarios key."
    )


def repair_json_with_llm(
    ticket_id: str,
    malformed_json_text: str,
    original_error: Exception,
):
    """
    Ask LLM to repair malformed scenario JSON once.

    This handles common LLM JSON issues:
    - unescaped double quotes inside strings
    - raw newlines inside strings
    - trailing commas
    - missing closing quotes
    """

    logger.warning(
        "Attempting to repair malformed scenarios JSON. ticket_id=%s, error=%s",
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
- Fix unescaped double quotes inside string values.
- Fix missing quotes.
- Fix unescaped newlines inside strings.
- Fix trailing commas.
- Do not invent new scenarios.
- Do not remove valid scenarios.
- Every string must start and end on the same line.
- Prefer single quotes inside string values when quoting messages, for example 'Email is required'.

Original parse error:
{original_error}

Malformed JSON:
{malformed_json_text}
"""

    llm = get_llm()

    response = llm.invoke(
        repair_prompt,
        ticket_id=ticket_id,
        node_name="generate_scenarios_json_repair",
    )

    repaired_raw_file = save_raw_response(
        ticket_id,
        "generate_scenarios_repaired_raw",
        response.content,
    )

    logger.info(
        "Repaired scenarios JSON response saved. ticket_id=%s, file=%s",
        ticket_id,
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


def _extract_functions(structure: dict) -> list[dict]:
    if not isinstance(structure, dict):
        return []

    functions = (
        structure.get("main_functions")
        or structure.get("functions")
        or structure.get("test_functions")
        or []
    )

    if not isinstance(functions, list):
        return []

    return functions


def _extract_sub_functions(function_item: dict) -> list[dict]:
    if not isinstance(function_item, dict):
        return []

    sub_functions = (
        function_item.get("sub_functions")
        or function_item.get("subfunctions")
        or function_item.get("children")
        or []
    )

    if not isinstance(sub_functions, list):
        return []

    return sub_functions


def _extract_test_areas(sub_function_item: dict) -> list[dict]:
    if not isinstance(sub_function_item, dict):
        return []

    test_areas = (
        sub_function_item.get("test_areas")
        or sub_function_item.get("detailed_test_areas")
        or sub_function_item.get("areas")
        or []
    )

    if not isinstance(test_areas, list):
        return []

    return test_areas


def _get_function_id(function_item: dict) -> str:
    return (
        function_item.get("function_id")
        or function_item.get("main_function_id")
        or function_item.get("id")
        or ""
    )


def _get_sub_function_id(sub_function_item: dict) -> str:
    return (
        sub_function_item.get("sub_function_id")
        or sub_function_item.get("subfunction_id")
        or sub_function_item.get("id")
        or ""
    )


def _get_test_area_id(test_area_item: dict) -> str:
    return (
        test_area_item.get("test_area_id")
        or test_area_item.get("area_id")
        or test_area_item.get("id")
        or ""
    )


def _build_structure_requirement_index(
    approved_structure: dict,
) -> dict[str, list[str]]:
    """
    Build lookup:
    - FUNC001 -> related requirement IDs
    - SUBFUNC001/SUB001 -> related requirement IDs
    - AREA001/CAT001 -> related requirement IDs
    """

    index: dict[str, list[str]] = {}

    for function_item in _extract_functions(approved_structure):
        function_id = _get_function_id(function_item)
        function_requirement_ids = _get_related_requirement_ids(function_item)

        if function_id and function_requirement_ids:
            index[function_id] = function_requirement_ids

        for sub_function_item in _extract_sub_functions(function_item):
            sub_function_id = _get_sub_function_id(sub_function_item)

            sub_function_requirement_ids = _unique_ids(
                function_requirement_ids
                + _get_related_requirement_ids(sub_function_item)
            )

            if sub_function_id and sub_function_requirement_ids:
                index[sub_function_id] = sub_function_requirement_ids

            for test_area_item in _extract_test_areas(sub_function_item):
                test_area_id = _get_test_area_id(test_area_item)

                test_area_requirement_ids = _unique_ids(
                    sub_function_requirement_ids
                    + _get_related_requirement_ids(test_area_item)
                )

                if test_area_id and test_area_requirement_ids:
                    index[test_area_id] = test_area_requirement_ids

    return index


def enrich_scenarios_traceability(
    scenarios: list,
    approved_structure: dict,
) -> tuple[list, list]:
    structure_index = _build_structure_requirement_index(approved_structure)

    enriched_scenarios = []
    filtered_scenarios = []

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            filtered_scenarios.append(
                {
                    "reason": "Scenario is not an object",
                    "scenario": scenario,
                }
            )
            continue

        related_requirement_ids = _get_related_requirement_ids(scenario)

        if not related_requirement_ids:
            candidate_ids = []

            for key in ["test_area_id", "sub_function_id", "function_id"]:
                structure_id = scenario.get(key)

                if structure_id and structure_id in structure_index:
                    candidate_ids.extend(structure_index[structure_id])

            related_requirement_ids = _unique_ids(candidate_ids)

        if not related_requirement_ids:
            filtered_scenarios.append(
                {
                    "reason": (
                        "No related_requirement_ids and cannot infer "
                        "from approved structure"
                    ),
                    "scenario": scenario,
                }
            )
            continue

        scenario["related_requirement_ids"] = related_requirement_ids
        scenario["traceability"] = ", ".join(related_requirement_ids)

        enriched_scenarios.append(scenario)

    return enriched_scenarios, filtered_scenarios


def validate_scenarios(scenarios: list) -> None:
    if not scenarios:
        raise ValueError("No valid traceable scenarios generated.")

    invalid_items = []

    for item in scenarios:
        if not isinstance(item, dict):
            invalid_items.append(item)
            continue

        if not item.get("scenario_id"):
            invalid_items.append(item)
            continue

        if not item.get("related_requirement_ids"):
            invalid_items.append(item)
            continue

        if not item.get("traceability"):
            invalid_items.append(item)
            continue

    if invalid_items:
        raise ValueError(
            f"Invalid scenario schema. First invalid item: {invalid_items[0]}"
        )
        
    
def _get_scenario_structure_batch_size() -> int:
    configured_value = os.getenv("SCENARIO_STRUCTURE_BATCH_SIZE", "5")

    try:
        batch_size = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid SCENARIO_STRUCTURE_BATCH_SIZE value: %s. Falling back to 5.",
            configured_value,
        )
        batch_size = 5

    return max(batch_size, 1)


def _get_scenario_parallel_workers(batch_count: int) -> int:
    configured_value = os.getenv("SCENARIO_PARALLEL_WORKERS", "2")

    try:
        configured_workers = int(configured_value)
    except ValueError:
        logger.warning(
            "Invalid SCENARIO_PARALLEL_WORKERS value: %s. Falling back to 2.",
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


def _build_structure_batches(
    approved_structure: dict,
) -> list[dict]:
    """
    Split approved structure into small batches by test areas.

    Each batch keeps:
    - one main function
    - one or more sub functions
    - limited number of test areas
    """

    batch_size = _get_scenario_structure_batch_size()
    batches = []

    for function_item in _extract_functions(approved_structure):
        function_id = _get_function_id(function_item)

        sub_functions = _extract_sub_functions(function_item)

        if not sub_functions:
            batches.append(
                {
                    "batch_id": f"{function_id}_batch_1",
                    "structure": {
                        "main_functions": [function_item],
                    },
                }
            )
            continue

        test_area_paths = []

        for sub_function_item in sub_functions:
            test_areas = _extract_test_areas(sub_function_item)

            if not test_areas:
                test_area_paths.append(
                    {
                        "sub_function": sub_function_item,
                        "test_area": None,
                    }
                )
                continue

            for test_area_item in test_areas:
                test_area_paths.append(
                    {
                        "sub_function": sub_function_item,
                        "test_area": test_area_item,
                    }
                )

        chunks = _chunk_list(test_area_paths, batch_size)

        for batch_index, chunk in enumerate(chunks, start=1):
            sub_function_map = {}

            for item in chunk:
                sub_function_item = item["sub_function"]
                test_area_item = item["test_area"]

                sub_function_id = _get_sub_function_id(sub_function_item)

                if sub_function_id not in sub_function_map:
                    copied_sub_function = dict(sub_function_item)
                    copied_sub_function["test_areas"] = []
                    sub_function_map[sub_function_id] = copied_sub_function

                if test_area_item:
                    sub_function_map[sub_function_id]["test_areas"].append(
                        test_area_item
                    )

            copied_function = dict(function_item)
            copied_function["sub_functions"] = list(sub_function_map.values())

            batches.append(
                {
                    "batch_id": f"{function_id}_batch_{batch_index}",
                    "function_id": function_id,
                    "batch_index": batch_index,
                    "structure": {
                        "main_functions": [copied_function],
                    },
                }
            )

    return batches


def _renumber_scenarios(scenarios: list) -> list:
    renumbered = []

    for index, scenario in enumerate(scenarios, start=1):
        item = dict(scenario)
        item["scenario_id"] = f"SC{index:03d}"
        renumbered.append(item)

    return renumbered


def _deduplicate_scenarios(scenarios: list) -> list:
    """
    Deduplicate scenarios by function/sub-function/test-area/title/type.
    """

    result = []
    seen = set()

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue

        key = (
            scenario.get("function_id", ""),
            scenario.get("sub_function_id", ""),
            scenario.get("test_area_id", ""),
            scenario.get("title", ""),
            scenario.get("type", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(scenario)

    return result


def _generate_scenarios_for_structure_batch(
    ticket_id: str,
    requirement_summary: dict,
    test_scope: dict,
    requirement_items: list,
    approved_structure: dict,
    structure_batch: dict,
) -> dict:
    batch_id = structure_batch["batch_id"]

    logger.info(
        "Generating scenarios for structure batch. ticket_id=%s, batch_id=%s",
        ticket_id,
        batch_id,
    )

    llm = get_llm()
    prompt = load_prompt("prompts/generate_structure_batch_scenarios.md")

    final_prompt = (
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
            "{requirement_items}",
            json.dumps(
                requirement_items,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{approved_test_case_structure_batch}",
            json.dumps(
                structure_batch["structure"],
                indent=2,
                ensure_ascii=False,
            ),
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name=f"generate_scenarios_{batch_id}",
    )

    raw_file = save_raw_response(
        ticket_id,
        f"generate_scenarios_{batch_id}_raw",
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

        scenarios = normalize_scenarios(parsed)

        scenarios, filtered_scenarios = enrich_scenarios_traceability(
            scenarios,
            approved_structure,
        )

        if filtered_scenarios:
            save_raw_response(
                ticket_id,
                f"generate_scenarios_{batch_id}_filtered",
                json.dumps(
                    filtered_scenarios,
                    indent=2,
                    ensure_ascii=False,
                ),
            )

        validate_scenarios(scenarios)

    except Exception as error:
        error_file = save_raw_response(
            ticket_id,
            f"generate_scenarios_{batch_id}_parse_error",
            (
                f"Failed to parse or validate scenarios for batch {batch_id}.\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        raise ValueError(
            f"Failed to generate scenarios for batch {batch_id}.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    logger.info(
        "Generated scenarios for structure batch. ticket_id=%s, batch_id=%s, scenario_count=%s",
        ticket_id,
        batch_id,
        len(scenarios),
    )

    return {
        "batch_id": batch_id,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "raw_file": raw_file,
    }


def generate_scenarios(state):
    ticket_id = state["ticket_id"]

    logger.info(
        "Starting batch-based scenario generation. ticket_id=%s",
        ticket_id,
    )

    approved_structure = state.get("approved_test_case_structure", {})

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for batch-based scenario generation."
        )

    structure_batches = _build_structure_batches(
        approved_structure
    )

    if not structure_batches:
        raise ValueError(
            "No structure batches could be created from approved_test_case_structure."
        )

    worker_count = _get_scenario_parallel_workers(
        len(structure_batches)
    )

    logger.info(
        "Structure split into scenario batches. ticket_id=%s, batch_count=%s, worker_count=%s",
        ticket_id,
        len(structure_batches),
        worker_count,
    )

    batch_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {}

        for structure_batch in structure_batches:
            future = executor.submit(
                _generate_scenarios_for_structure_batch,
                ticket_id,
                state.get("requirement_summary", {}),
                state.get("test_scope", {}),
                state.get("analysis", {}).get("requirement_items", []),
                approved_structure,
                structure_batch,
            )

            future_map[future] = structure_batch["batch_id"]

        for future in as_completed(future_map):
            batch_id = future_map[future]

            try:
                batch_results.append(future.result())
            except Exception as error:
                logger.warning(
                    "Scenario batch generation failed. ticket_id=%s, batch_id=%s, error=%s",
                    ticket_id,
                    batch_id,
                    str(error).splitlines()[0],
                )

                errors.append(
                    {
                        "batch_id": batch_id,
                        "error": str(error),
                    }
                )

    if errors:
        error_file = save_raw_response(
            ticket_id,
            "generate_scenarios_batch_errors",
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            ),
        )

        raise ValueError(
            "One or more scenario batches failed.\n"
            f"Error details saved to: {error_file}\n"
            f"Errors: {errors}"
        )

    batch_results.sort(
        key=lambda item: item["batch_id"]
    )

    scenarios = []

    for batch_result in batch_results:
        scenarios.extend(batch_result["scenarios"])

    scenarios = _deduplicate_scenarios(scenarios)
    scenarios = _renumber_scenarios(scenarios)

    validate_scenarios(scenarios)

    save_scenarios(ticket_id, scenarios)

    manifest = {
        "generation_mode": "BATCH_BASED_SCENARIO_GENERATION",
        "batch_count": len(batch_results),
        "scenario_count": len(scenarios),
        "batches": [
            {
                "batch_id": result["batch_id"],
                "scenario_count": result["scenario_count"],
                "raw_file": result["raw_file"],
            }
            for result in batch_results
        ],
    }

    save_raw_response(
        ticket_id,
        "generate_scenarios_batch_manifest",
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    logger.info(
        "Batch-based scenario generation completed. ticket_id=%s, scenario_count=%s, batch_count=%s",
        ticket_id,
        len(scenarios),
        len(batch_results),
    )

    return {
        "scenarios": scenarios,
        "scenario_generation_manifest": manifest,
    }