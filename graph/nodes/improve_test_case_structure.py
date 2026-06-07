import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.test_structure_store import (
    save_latest_test_case_structure
)


def improve_test_case_structure(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/improve_test_case_structure.md"
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
        .replace(
            "{test_case_structure}",
            json.dumps(
                state.get("test_case_structure", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{structure_review}",
            json.dumps(
                state.get("test_case_structure_review", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{review_comments}",
            json.dumps(
                state.get("structure_review_comments", []),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="improve_test_case_structure"
    )

    try:
        improved_structure = parse_json(
            response.content
        )

    except Exception as error:
        improved_structure = {
            "main_functions": [],
            "raw_response": response.content,
            "parse_error": str(error)
        }

    save_latest_test_case_structure(
        state["ticket_id"],
        improved_structure
    )

    return {
        "test_case_structure": improved_structure
    }