import logging
import os
from contextvars import ContextVar
from typing import Any

from fastapi import HTTPException, Request

from app.services.ai_mode_context_service import (
    AI_MODE_DEEPSEEK_ONLY,
    AI_MODE_NO_LLM,
    AI_MODE_PRODUCTION_HYBRID,
    AI_MODE_PRODUCTION_REMOTE_ONLY,
    AI_MODE_TEST_LOCAL_ONLY,
    VALID_AI_MODES,
    get_portal_ai_mode_from_headers,
    normalize_ai_mode,
)


logger = logging.getLogger(__name__)

TEST_LOCAL_ONLY = AI_MODE_TEST_LOCAL_ONLY
PRODUCTION_HYBRID = AI_MODE_PRODUCTION_HYBRID
PRODUCTION_REMOTE_ONLY = AI_MODE_PRODUCTION_REMOTE_ONLY
DEEPSEEK_ONLY = AI_MODE_DEEPSEEK_ONLY
NO_LLM = AI_MODE_NO_LLM

_portal_ai_mode: ContextVar[dict[str, Any] | None] = ContextVar(
    "portal_ai_mode",
    default=None,
)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name, "").strip().lower()

    if not value:
        return default

    return value in {"1", "true", "yes", "y", "on"}


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _deepseek_available() -> bool:
    return bool(_env_str("DEEPSEEK_API_KEY")) and not _env_bool(
        "FORCE_DISABLE_DEEPSEEK",
        False,
    )


def _local_ai_available() -> bool:
    return bool(_env_str("LOCAL_BASE_URL")) and not _env_bool(
        "FORCE_DISABLE_LOCAL_AI",
        False,
    )


def _default_ai_mode() -> str:
    configured = normalize_ai_mode(os.getenv("PORTAL_DEFAULT_AI_MODE", NO_LLM))

    if configured in VALID_AI_MODES:
        return configured

    logger.warning(
        "Invalid PORTAL_DEFAULT_AI_MODE=%s; falling back to %s.",
        configured,
        NO_LLM,
    )
    return NO_LLM


def get_default_ai_mode() -> str:
    return _default_ai_mode()


def resolve_ai_mode_from_headers(headers: Any) -> dict[str, Any]:
    return get_portal_ai_mode_from_headers(headers)


def set_portal_ai_mode_for_request(headers: Any):
    resolved = resolve_ai_mode_from_headers(headers)
    return _portal_ai_mode.set(resolved)


def set_portal_ai_mode_context(ai_mode_context: dict[str, Any] | None):
    return _portal_ai_mode.set(ai_mode_context)


def reset_portal_ai_mode(token) -> None:
    _portal_ai_mode.reset(token)


def get_current_portal_ai_mode() -> dict[str, Any] | None:
    return _portal_ai_mode.get()


def is_deepseek_allowed_for_request(headers: Any | None = None) -> bool:
    mode = resolve_ai_mode_from_headers(headers) if headers is not None else _portal_ai_mode.get()

    if mode is None:
        return _deepseek_available()

    if not _deepseek_available():
        return False

    return mode.get("ai_mode") in {
        PRODUCTION_HYBRID,
        DEEPSEEK_ONLY,
    }


def is_local_ai_allowed_for_request(headers: Any | None = None) -> bool:
    mode = resolve_ai_mode_from_headers(headers) if headers is not None else _portal_ai_mode.get()

    if mode is None:
        return _local_ai_available()

    if not _local_ai_available():
        return False

    return mode.get("ai_mode") in {TEST_LOCAL_ONLY, PRODUCTION_HYBRID}


def assert_deepseek_allowed() -> None:
    if is_deepseek_allowed_for_request():
        return

    mode = _portal_ai_mode.get()
    message = "DeepSeek call blocked because DeepSeek is not available."

    if mode:
        if mode.get("ai_mode") == TEST_LOCAL_ONLY:
            message = "DeepSeek call blocked because Portal is in TEST_LOCAL_ONLY mode."
        elif mode.get("ai_mode") == NO_LLM:
            message = "DeepSeek call blocked because Portal is in NO_LLM mode."
        elif _env_bool("FORCE_DISABLE_DEEPSEEK", False):
            message = "DeepSeek call blocked because FORCE_DISABLE_DEEPSEEK=true."
        elif not _env_str("DEEPSEEK_API_KEY"):
            message = "DeepSeek call blocked because DEEPSEEK_API_KEY is missing."

    logger.warning(message)
    raise RuntimeError(message)


def assert_local_ai_allowed() -> None:
    if is_local_ai_allowed_for_request():
        return

    mode = _portal_ai_mode.get()
    message = "Local AI call skipped because Local AI is not available."

    if mode:
        if mode.get("ai_mode") == DEEPSEEK_ONLY:
            message = (
                "Local AI call skipped because Portal is in "
                "DEEPSEEK_ONLY mode."
            )
        elif mode.get("ai_mode") == NO_LLM:
            message = "Local AI call skipped because Portal is in NO_LLM mode."
        elif _env_bool("FORCE_DISABLE_LOCAL_AI", False):
            message = "Local AI call skipped because FORCE_DISABLE_LOCAL_AI=true."
        elif not _env_str("LOCAL_BASE_URL"):
            message = "Local AI call skipped because LOCAL_BASE_URL is missing."

    logger.warning(message)
    raise RuntimeError(message)


async def portal_ai_mode_dependency(request: Request):
    try:
        token = set_portal_ai_mode_for_request(request.headers)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        yield
    finally:
        reset_portal_ai_mode(token)
