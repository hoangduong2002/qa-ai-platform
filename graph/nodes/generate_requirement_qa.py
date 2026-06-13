import json

from app.services.llm_router_service import (
    TASK_REQUIREMENT_SUMMARY,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import (
    save_requirement_qa
)


def _resolve_ai_mode(state: dict | None = None) -> str | None:
    state = state or {}
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def generate_requirement_qa(
    state
):
    prompt = load_prompt(
        "prompts/generate_requirement_qa.md"
    )

    final_prompt = prompt.replace(
        "{analysis}",
        json.dumps(
            state.get(
                "analysis",
                {}
            ),
            indent=2,
            ensure_ascii=False
        )
    )

    response_content = call_text_llm(
        task_type=TASK_REQUIREMENT_SUMMARY,
        prompt=final_prompt,
        ai_mode=_resolve_ai_mode(state),
    )

    try:

        qa = parse_json(
            response_content
        )
        
        save_requirement_qa(
            state["ticket_id"],
            qa
        )

    except Exception:

        qa = {
            "raw_response":
            response_content
        }

    return {
        "requirement_qa": qa
    }
