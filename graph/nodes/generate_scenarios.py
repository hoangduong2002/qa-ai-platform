import json
import logging
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


def generate_scenarios(state):
    ticket_id = state["ticket_id"]

    logger.info(
        "Starting scenario generation. ticket_id=%s",
        ticket_id,
    )

    llm = get_llm()
    prompt = load_prompt("prompts/generate_scenarios.md")

    approved_structure = state.get("approved_test_case_structure", {})

    final_prompt = (
        prompt
        .replace(
            "{requirement_summary}",
            json.dumps(
                state.get("requirement_summary", {}),
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{test_scope}",
            json.dumps(
                state.get("test_scope", {}),
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{requirement_items}",
            json.dumps(
                state.get("analysis", {}).get("requirement_items", []),
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{approved_test_case_structure}",
            json.dumps(
                approved_structure,
                indent=2,
                ensure_ascii=False,
            ),
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=ticket_id,
        node_name="generate_scenarios",
    )

    raw_file = save_raw_response(
        ticket_id,
        "generate_scenarios_raw",
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
                "generate_scenarios_filtered",
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
            "generate_scenarios_parse_error",
            (
                "Failed to parse or validate scenarios JSON.\n\n"
                f"Error:\n{error}\n\n"
                f"Raw response file:\n{raw_file}\n"
            ),
        )

        logger.exception(
            "Scenario generation failed. ticket_id=%s",
            ticket_id,
        )

        raise ValueError(
            "Failed to parse scenarios JSON.\n"
            f"Raw response saved to: {raw_file}\n"
            f"Parse debug saved to: {error_file}\n"
            f"Original error: {error}"
        ) from error

    save_scenarios(ticket_id, scenarios)

    logger.info(
        "Scenario generation completed. ticket_id=%s, scenario_count=%s",
        ticket_id,
        len(scenarios),
    )

    return {
        "scenarios": scenarios,
    }