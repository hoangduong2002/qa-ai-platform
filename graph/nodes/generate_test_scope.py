import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.file_writer import (
    save_test_scope
)


def generate_test_scope(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_test_scope.md"
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
        node_name="generate_test_scope"
    )

    try:
        test_scope = parse_json(
            response.content
        )

    except Exception as error:
        test_scope = {
            "raw_response": response.content,
            "parse_error": str(error)
        }

    save_test_scope(
        state["ticket_id"],
        test_scope
    )

    return {
        "test_scope": test_scope
    }