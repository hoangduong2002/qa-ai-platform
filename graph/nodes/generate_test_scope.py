import json

from app.services.llm_router_service import (
    TASK_SCENARIO_GENERATION,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.file_writer import (
    save_test_scope
)


def _resolve_ai_mode(state: dict | None = None) -> str | None:
    state = state or {}
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def generate_test_scope(state):

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

    response_content = call_text_llm(
        TASK_SCENARIO_GENERATION,
        final_prompt,
        ai_mode=_resolve_ai_mode(state),
    )

    try:
        test_scope = parse_json(
            response_content
        )

    except Exception as error:
        test_scope = {
            "raw_response": response_content,
            "parse_error": str(error)
        }

    save_test_scope(
        state["ticket_id"],
        test_scope
    )

    return {
        "test_scope": test_scope
    }
