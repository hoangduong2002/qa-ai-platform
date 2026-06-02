import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import save_improved_testcases


def improve_testcases(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/improve_testcases.md"
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
    )

    response = llm.invoke(
        final_prompt
    )

    try:

        improved_testcases = parse_json(
            response.content
        )

        improve_version = state.get(
            "improve_version",
            "latest"
        )

        save_improved_testcases(
            state["ticket_id"],
            improved_testcases,
            version=improve_version
        )

    except Exception:

        improved_testcases = [
            {
                "raw_response": response.content
            }
        ]

    return {
        "improved_testcases": improved_testcases
    }