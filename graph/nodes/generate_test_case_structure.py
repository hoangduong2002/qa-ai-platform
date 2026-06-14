import json
import logging

from app.services.llm_router_service import (
    TASK_TEST_STRUCTURE,
    call_text_llm,
)
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.test_structure_store import (
    save_latest_test_case_structure
)


logger = logging.getLogger(__name__)


def _resolve_ai_mode(state: dict) -> str | None:
    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()

    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def generate_test_case_structure(state):
    metadata = state.get("requirement_context_metadata") or {}
    ai_mode = _resolve_ai_mode(state)

    if metadata:
        print(
            "generate_test_case_structure context_source="
            f"{metadata.get('context_source')}, "
            f"length={metadata.get('context_length')}, "
            f"path={metadata.get('context_path')}"
        )
        logger.info(
            "Text reasoning node task_type=%s ai_mode=%s context_source=%s",
            TASK_TEST_STRUCTURE,
            ai_mode or "default",
            metadata.get("context_source"),
        )

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

    content = call_text_llm(
        task_type=TASK_TEST_STRUCTURE,
        prompt=final_prompt,
        ai_mode=ai_mode,
        source_channel=state.get("source_channel"),
    )

    try:
        structure = parse_json(
            content
        )

    except Exception as error:
        structure = {
            "main_functions": [],
            "raw_response": content,
            "parse_error": str(error)
        }

    save_latest_test_case_structure(
        state["ticket_id"],
        structure
    )

    return {
        "test_case_structure": structure
    }
