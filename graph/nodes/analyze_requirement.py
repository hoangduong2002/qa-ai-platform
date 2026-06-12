import logging

from app.services.llm_router_service import (
    AI_MODE_TEST_LOCAL_ONLY,
    TASK_REQUIREMENT_ANALYSIS,
    call_text_llm,
    resolve_provider_for_task,
)
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import (
    save_analysis,
    save_analysis_raw_response,
    save_analysis_parse_error,
    save_analysis_error,
    save_requirement_items,
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


def _assert_json_response(
    content: str,
    raw_response_path: str | None = None,
    ai_mode: str | None = None,
) -> None:
    if not isinstance(content, str):
        raise RuntimeError(
            "Requirement analysis LLM returned an invalid non-text response."
        )

    stripped = content.strip()
    if not stripped:
        raise RuntimeError(
            "Requirement analysis LLM returned an empty response. Expected strict JSON output."
        )

    if stripped.startswith("[SKIPPED]") or stripped.startswith("[ERROR]"):
        raise RuntimeError(
            "LLM provider did not return a valid JSON response. "
            "Please check AI mode and provider configuration."
        )

    if stripped[0] != "{" or stripped[-1] != "}":
        if ai_mode == AI_MODE_TEST_LOCAL_ONLY:
            message = (
                "Local model returned non-JSON. Try Production mode or improve prompt/model."
            )
        else:
            message = (
                "Requirement analysis LLM returned non-JSON text. Expected strict JSON object."
            )

        if raw_response_path:
            message += f" Check raw response at {raw_response_path}."

        raise RuntimeError(message)


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

    try:
        content = call_text_llm(
            task_type=TASK_REQUIREMENT_ANALYSIS,
            prompt=final_prompt,
            ai_mode=ai_mode,
        )
    except Exception as error:
        error_content = (
            "Requirement analysis failed during LLM execution.\n"
            f"Error: {error}\n"
        )

        save_analysis_error(
            state["ticket_id"],
            error_content,
        )

        raise

    raw_response_path = save_analysis_raw_response(
        state["ticket_id"],
        content,
    )

    logger.info(
        "Requirement analysis raw response preview=%s",
        content.replace("\n", " ").strip()[:500],
    )

    provider_info = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        ai_mode or "",
    )

    try:
        _assert_json_response(
            content,
            raw_response_path=raw_response_path,
            ai_mode=ai_mode,
        )
        analysis = parse_json(
            content,
            label="requirement analysis response"
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

    except Exception as error:
        response_preview = content.replace("\n", " ").strip()[:500]
        parse_error_content = (
            "Requirement analysis parse failure.\n"
            f"Error: {error}\n"
            f"Provider: {provider_info.get('provider')}\n"
            f"AI mode: {provider_info.get('ai_mode')}\n"
            f"Model: {provider_info.get('model')}\n"
            f"Raw response preview: {response_preview}\n"
            f"Raw response path: {raw_response_path}\n"
        )

        save_analysis_parse_error(
            state["ticket_id"],
            parse_error_content,
        )

        raise RuntimeError(
            "Requirement analysis response failed to parse JSON. "
            f"Check raw response at {raw_response_path}."
        ) from error

    return {
        "analysis": analysis
    }
