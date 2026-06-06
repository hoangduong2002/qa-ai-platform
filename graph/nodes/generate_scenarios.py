import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.file_writer import (
    save_scenarios
)


def normalize_scenarios(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in [
            "scenarios",
            "test_scenarios",
            "testScenarios"
        ]:
            if isinstance(data.get(key), list):
                return data[key]

    return [
        {
            "raw_response": data
        }
    ]


def generate_scenarios(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_scenarios.md"
    )

    final_prompt = (
        prompt
        .replace(
            "{requirement_summary}",
            json.dumps(
                state.get("requirement_summary", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{test_scope}",
            json.dumps(
                state.get("test_scope", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{requirement_items}",
            json.dumps(
                state.get(
                    "analysis",
                    {}
                ).get(
                    "requirement_items",
                    []
                ),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="generate_scenarios"
    )

    try:
        parsed = parse_json(
            response.content
        )

        scenarios = normalize_scenarios(
            parsed
        )

    except Exception as error:
        scenarios = [
            {
                "raw_response": response.content,
                "parse_error": str(error)
            }
        ]

    save_scenarios(
        state["ticket_id"],
        scenarios
    )

    return {
        "scenarios": scenarios
    }