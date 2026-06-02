import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import save_test_scope
from app.utils.llm_json import parse_json


def generate_test_scope(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_test_scope.md"
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
            "{clarifications}",
            json.dumps(
                state.get("clarifications", {}),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(final_prompt)

    try:
        test_scope = parse_json(
            response.content
        )

        save_test_scope(
            state.get("ticket_id"),
            test_scope
        )

    except Exception:
        test_scope = {
            "raw_response": response.content
        }

    return {
        "test_scope": test_scope
    }