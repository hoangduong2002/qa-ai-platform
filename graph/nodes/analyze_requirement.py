import logging

from app.services.llm_router_service import (
    TASK_REQUIREMENT_ANALYSIS,
    call_text_llm,
)
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import (
    save_analysis,
    save_requirement_items
)
from app.utils.llm_json import parse_json


logger = logging.getLogger(__name__)


def _resolve_ai_mode(state: dict) -> str | None:
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()

    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def analyze_requirement(state):
    metadata = state.get("requirement_context_metadata") or {}
    ai_mode = _resolve_ai_mode(state)

    if metadata:
        print(
            "analyze_requirement context_source="
            f"{metadata.get('context_source')}, "
            f"length={metadata.get('context_length')}, "
            f"path={metadata.get('context_path')}"
        )
        logger.info(
            "Text reasoning node task_type=%s ai_mode=%s context_source=%s",
            TASK_REQUIREMENT_ANALYSIS,
            ai_mode or "default",
            metadata.get("context_source"),
        )

    prompt = load_prompt(
        "prompts/analyze_requirement.md"
    )

    final_prompt = prompt.replace(
        "{requirement_context}",
        state.get("requirement_context", "")
    )

    content = call_text_llm(
        task_type=TASK_REQUIREMENT_ANALYSIS,
        prompt=final_prompt,
        ai_mode=ai_mode,
    )

    try:
        analysis = parse_json(
            content
        )

        save_analysis(
            state["ticket_id"],
            analysis
        )

        requirement_items = analysis.get(
            "requirement_items",
            []
        )

        save_requirement_items(
            state["ticket_id"],
            requirement_items
        )

    except Exception:
        analysis = {
            "raw_response": content
        }

    return {
        "analysis": analysis
    }
