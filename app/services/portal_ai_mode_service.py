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
    DEEPSEEK_ONLY,
    NO_LLM,
}

BACKWARD_COMPATIBLE_AI_MODE_ALIASES = {
    PRODUCTION_REMOTE_ONLY: DEEPSEEK_ONLY,
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


def _default_ai_mode() -> str:
    configured = os.getenv("PORTAL_DEFAULT_AI_MODE", NO_LLM).strip().upper()
    configured = BACKWARD_COMPATIBLE_AI_MODE_ALIASES.get(configured, configured)

    if configured in VALID_AI_MODES:
        return configured

    logger.warning(
        "Invalid PORTAL_DEFAULT_AI_MODE=%s; falling back to %s.",
        configured,
        NO_LLM,
    )
    return NO_LLM


def _derive_ai_mode_from_legacy_headers(headers: Any) -> str:
    production_header = headers.get("X-Production-Mode")
    local_header = headers.get("X-Local-AI-Enabled")

    if production_header is None and local_header is None:
        return _default_ai_mode()

    production_mode = _header_bool(headers, "X-Production-Mode", False)
    local_ai_enabled = _header_bool(headers, "X-Local-AI-Enabled", False)

    if production_mode and local_ai_enabled:
        return PRODUCTION_HYBRID

    if production_mode and not local_ai_enabled:
        return DEEPSEEK_ONLY

    if local_ai_enabled:
        return TEST_LOCAL_ONLY

    return NO_LLM


def resolve_ai_mode_from_headers(headers: Any) -> dict[str, Any]:
    requested_ai_mode = str(headers.get("X-AI-Mode") or "").strip().upper()

    if not requested_ai_mode:
        requested_ai_mode = _derive_ai_mode_from_legacy_headers(headers)

    requested_ai_mode = BACKWARD_COMPATIBLE_AI_MODE_ALIASES.get(
        requested_ai_mode,
        requested_ai_mode,
    )

    if requested_ai_mode not in VALID_AI_MODES:
        raise ValueError(f"Invalid AI mode: {requested_ai_mode}")

    return {
        "ai_mode": requested_ai_mode,
        "production_mode": requested_ai_mode
        in {PRODUCTION_HYBRID, DEEPSEEK_ONLY},
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
        PRODUCTION_HYBRID,
        DEEPSEEK_ONLY,
    }


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
        if mode.get("ai_mode") == DEEPSEEK_ONLY:
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
