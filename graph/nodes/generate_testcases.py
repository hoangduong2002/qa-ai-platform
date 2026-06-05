import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_testcases


def normalize_testcases(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in [
            "testcases",
            "test_cases",
            "testCases"
        ]:

            if isinstance(
                data.get(key),
                list
            ):
                return data[key]

    return [
        {
            "raw_response": data
        }
    ]


def generate_testcases(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_testcases.md"
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
            "{scenarios}",
            json.dumps(
                state.get("scenarios", []),
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
            "{clarifications}",
            json.dumps(
                state.get("clarifications", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{clarification_answers}",
            json.dumps(
                state.get("clarification_answers", {}),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="generate_testcases"
    )

    try:
        parsed = parse_json(
            response.content
        )

        testcases = normalize_testcases(
            parsed
        )

    except Exception as error:
        testcases = [
            {
                "raw_response": response.content,
                "parse_error": str(error)
            }
        ]

    save_testcases(
        state["ticket_id"],
        testcases
    )

    return {
        "testcases": testcases
    }