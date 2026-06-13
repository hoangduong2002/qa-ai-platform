import json

from app.services.llm_router_service import (
    TASK_TEST_STRUCTURE,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.test_structure_store import (
    save_latest_test_case_structure
)


def _resolve_ai_mode(state: dict | None = None) -> str | None:
    state = state or {}
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def improve_test_case_structure(state):
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

    response_content = call_text_llm(
        task_type=TASK_TEST_STRUCTURE,
        prompt=final_prompt,
        ai_mode=_resolve_ai_mode(state),
    )

    try:
        improved_structure = parse_json(
            response_content
        )

    except Exception as error:
        improved_structure = {
            "main_functions": [],
            "raw_response": response_content,
            "parse_error": str(error)
        }

    save_latest_test_case_structure(
        state["ticket_id"],
        improved_structure
    )

    return {
        "test_case_structure": improved_structure
    }
