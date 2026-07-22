from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.models.structured_analysis_schema import (
    StructuredRequirementAnalysisV1,
    validate_structured_requirement_analysis,
)
from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm
from app.utils.file_writer import (
    save_structured_analysis,
    save_structured_analysis_error,
    save_structured_analysis_parse_error,
    save_structured_analysis_raw_response,
)
from app.utils.llm_json import parse_json
from app.utils.prompt_loader import load_prompt


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def structured_analysis_enabled() -> bool:
    return _env_bool("STRUCTURED_ANALYSIS_ENABLED", False)


def structured_analysis_shadow_mode() -> bool:
    return _env_bool("STRUCTURED_ANALYSIS_SHADOW_MODE", False)


def _structured_analysis_prompt(requirement_context: str) -> str:
    prompt = load_prompt("prompts/analyze_requirement_structured.md")
    return prompt.replace("{requirement_context}", requirement_context or "")


def _error_path(ticket_id: str) -> str:
    return str(Path("requirements") / ticket_id / "analysis" / "structured_analysis_error.txt")


def run_structured_requirement_analysis_shadow(state: dict) -> dict[str, Any]:
    if not structured_analysis_enabled():
        return {}

    ticket_id = state["ticket_id"]
    shadow_mode = structured_analysis_shadow_mode()
    ai_mode = state.get("ai_mode")
    prompt = _structured_analysis_prompt(state.get("requirement_context", ""))

    max_attempts = 2
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            content = call_text_llm(
                task_type=TASK_REQUIREMENT_ANALYSIS,
                prompt=prompt,
                ai_mode=ai_mode,
                source_channel=state.get("source_channel"),
            )

            raw_path = save_structured_analysis_raw_response(
                ticket_id,
                content,
                attempt=attempt,
            )

            payload = parse_json(content, label="structured requirement analysis response")
            structured: StructuredRequirementAnalysisV1 = validate_structured_requirement_analysis(payload)
            save_structured_analysis(ticket_id, structured.model_dump())

            return {
                "structured_analysis": structured.model_dump(),
                "structured_analysis_metadata": {
                    "enabled": True,
                    "shadow_mode": shadow_mode,
                    "active_for_downstream": not shadow_mode,
                    "attempts": attempt,
                    "raw_response_path": raw_path,
                    "schema_valid": True,
                },
            }

        except Exception as error:
            last_error = error
            save_structured_analysis_parse_error(
                ticket_id=ticket_id,
                error_content=(
                    "Structured requirement analysis parse/validation failure.\n"
                    f"Attempt: {attempt}\n"
                    f"Error: {error}\n"
                ),
                attempt=attempt,
            )

            # Conservative retry with explicit repair instruction and no default invention.
            prompt = (
                _structured_analysis_prompt(state.get("requirement_context", ""))
                + "\n\n"
                + "Previous output failed validation. Return strict schema-valid JSON only. "
                + "Do not invent missing values; use null or empty arrays where unsupported. "
                + f"Validation error: {error}"
            )

    error_message = (
        "Structured requirement analysis shadow execution failed. "
        "Authoritative requirement analysis remains unchanged.\n"
        f"Error: {last_error}"
    )
    save_structured_analysis_error(ticket_id, error_message)

    return {
        "structured_analysis_error": str(last_error or "unknown error"),
        "structured_analysis_metadata": {
            "enabled": True,
            "shadow_mode": shadow_mode,
            "active_for_downstream": False,
            "attempts": max_attempts,
            "schema_valid": False,
            "error_path": _error_path(ticket_id),
        },
    }
