import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.test_structure_store import (
    save_latest_test_case_structure
)


def generate_test_case_structure(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_test_case_structure.md"
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
            "{requirement_items}",
            json.dumps(
                state.get("analysis", {}).get(
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
        node_name="generate_test_case_structure"
    )

    try:
        structure = parse_json(
            response.content
        )

    except Exception as error:
        structure = {
            "main_functions": [],
            "raw_response": response.content,
            "parse_error": str(error)
        }

    save_latest_test_case_structure(
        state["ticket_id"],
        structure
    )

    return {
        "test_case_structure": structure
    }