import logging
import os
from contextvars import ContextVar
from typing import Any

from fastapi import HTTPException, Request


logger = logging.getLogger(__name__)

TEST_LOCAL_ONLY = "TEST_LOCAL_ONLY"
PRODUCTION_HYBRID = "PRODUCTION_HYBRID"
PRODUCTION_REMOTE_ONLY = "PRODUCTION_REMOTE_ONLY"
DEEPSEEK_ONLY = "DEEPSEEK_ONLY"
NO_LLM = "NO_LLM"

VALID_AI_MODES = {
    TEST_LOCAL_ONLY,
    PRODUCTION_HYBRID,
    PRODUCTION_REMOTE_ONLY,
    DEEPSEEK_ONLY,
    NO_LLM,
}

_portal_ai_mode: ContextVar[dict[str, Any] | None] = ContextVar(
    "portal_ai_mode",
    default=None,
)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name, "").strip().lower()

    if not value:
        return default

    return value in {"1", "true", "yes", "y", "on"}


def _header_bool(headers: Any, name: str, default: bool) -> bool:
    value = headers.get(name)

    if value is None or str(value).strip() == "":
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_ai_mode_from_headers(headers: Any) -> dict[str, Any]:
    requested_ai_mode = str(headers.get("X-AI-Mode") or "").strip().upper()

    if not requested_ai_mode:
        requested_ai_mode = NO_LLM

    if requested_ai_mode not in VALID_AI_MODES:
        raise ValueError(f"Invalid AI mode: {requested_ai_mode}")

    return {
        "ai_mode": requested_ai_mode,
        "production_mode": requested_ai_mode
        in {PRODUCTION_HYBRID, PRODUCTION_REMOTE_ONLY, DEEPSEEK_ONLY},
        "local_ai_enabled": requested_ai_mode
        in {PRODUCTION_HYBRID, TEST_LOCAL_ONLY},
        "deepseek_enabled": _env_bool("DEEPSEEK_ENABLED", True),
        "server_local_ai_enabled": _env_bool("LOCAL_AI_ENABLED", True),
        "source": "portal",
    }


def set_portal_ai_mode_for_request(headers: Any):
    resolved = resolve_ai_mode_from_headers(headers)
    return _portal_ai_mode.set(resolved)


def reset_portal_ai_mode(token) -> None:
    _portal_ai_mode.reset(token)


def get_current_portal_ai_mode() -> dict[str, Any] | None:
    return _portal_ai_mode.get()


def is_deepseek_allowed_for_request(headers: Any | None = None) -> bool:
    mode = resolve_ai_mode_from_headers(headers) if headers is not None else _portal_ai_mode.get()

    if mode is None:
        return _env_bool("DEEPSEEK_ENABLED", True)

    if not mode.get("deepseek_enabled", True):
        return False

    return mode.get("ai_mode") in {
        TEST_LOCAL_ONLY,
        PRODUCTION_HYBRID,
        PRODUCTION_REMOTE_ONLY,
        DEEPSEEK_ONLY,
    } and mode.get("ai_mode") != TEST_LOCAL_ONLY


def is_local_ai_allowed_for_request(headers: Any | None = None) -> bool:
    mode = resolve_ai_mode_from_headers(headers) if headers is not None else _portal_ai_mode.get()

    if mode is None:
        return _env_bool("LOCAL_AI_ENABLED", True)

    if not mode.get("server_local_ai_enabled", True):
        return False

    return mode.get("ai_mode") in {TEST_LOCAL_ONLY, PRODUCTION_HYBRID}


def assert_deepseek_allowed() -> None:
    if is_deepseek_allowed_for_request():
        return

    mode = _portal_ai_mode.get()
    message = "DeepSeek call blocked because DEEPSEEK_ENABLED=false."

    if mode:
        if mode.get("ai_mode") == TEST_LOCAL_ONLY:
            message = "DeepSeek call blocked because Portal is in TEST_LOCAL_ONLY mode."
        elif mode.get("ai_mode") == NO_LLM:
            message = "DeepSeek call blocked because Portal is in NO_LLM mode."
        elif mode.get("ai_mode") == DEEPSEEK_ONLY:
            message = "DeepSeek call blocked because DEEPSEEK_ENABLED=false."

    logger.warning(message)
    raise RuntimeError(message)


def assert_local_ai_allowed() -> None:
    if is_local_ai_allowed_for_request():
        return

    mode = _portal_ai_mode.get()
    message = "Local AI call skipped because LOCAL_AI_ENABLED=false."

    if mode:
        if mode.get("ai_mode") == PRODUCTION_REMOTE_ONLY:
            message = (
                "Local AI call skipped because Portal is in "
                "PRODUCTION_REMOTE_ONLY mode."
            )
        elif mode.get("ai_mode") == DEEPSEEK_ONLY:
            message = (
                "Local AI call skipped because Portal is in "
                "DEEPSEEK_ONLY mode."
            )
        elif mode.get("ai_mode") == NO_LLM:
            message = "Local AI call skipped because Portal is in NO_LLM mode."

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
