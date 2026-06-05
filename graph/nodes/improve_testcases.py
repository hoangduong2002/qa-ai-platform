import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_improved_testcases

from app.utils.testcase_merge import (
    merge_renumber_and_save_testcases
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
            "testCases"
        ]:
            if isinstance(data.get(key), list):
                return data[key]

    return [
        {
            "raw_response": data
        }
    ]


def improve_testcases(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/improve_testcases.md"
    )

    improve_version = state.get(
        "improve_version",
        "latest"
    )

    final_prompt = (
        prompt
        .replace(
            "{analysis}",
            json.dumps(
                state.get("analysis", {}),
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
            "{testcases}",
            json.dumps(
                state.get("testcases", []),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{coverage_review}",
            json.dumps(
                state.get("coverage_review", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{review_comments}",
            json.dumps(
                state.get("review_comments", []),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="improve_testcases"
    )

    try:

        parsed = parse_json(
            response.content
        )

        improved_testcases = normalize_testcases(
            parsed
        )

    except Exception as error:

        improved_testcases = [
            {
                "raw_response": response.content,
                "parse_error": str(error)
            }
        ]

    save_improved_testcases(
        state["ticket_id"],
        improved_testcases,
        version=improve_version
    )

    merged_testcases = merge_renumber_and_save_testcases(
        state["ticket_id"],
        state.get("testcases", []),
        improved_testcases
    )

    return {
        "improved_testcases": merged_testcases,
        "testcases": merged_testcases
    }