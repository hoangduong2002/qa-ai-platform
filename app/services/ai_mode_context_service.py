import logging
import os
from typing import Any


logger = logging.getLogger(__name__)

AI_MODE_TEST_LOCAL_ONLY = "TEST_LOCAL_ONLY"
AI_MODE_PRODUCTION_HYBRID = "PRODUCTION_HYBRID"
AI_MODE_PRODUCTION_REMOTE_ONLY = "PRODUCTION_REMOTE_ONLY"
AI_MODE_DEEPSEEK_ONLY = "DEEPSEEK_ONLY"
AI_MODE_NO_LLM = "NO_LLM"

VALID_AI_MODES = {
    AI_MODE_TEST_LOCAL_ONLY,
    AI_MODE_PRODUCTION_HYBRID,
    AI_MODE_DEEPSEEK_ONLY,
    AI_MODE_NO_LLM,
}

BACKWARD_COMPATIBLE_AI_MODE_ALIASES = {
    AI_MODE_PRODUCTION_REMOTE_ONLY: AI_MODE_DEEPSEEK_ONLY,
}

TELEGRAM_DEFAULT_AI_MODE = AI_MODE_PRODUCTION_HYBRID
PORTAL_DEFAULT_AI_MODE = AI_MODE_NO_LLM


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)

    if not value:
        return default

    return value.lower() in {"1", "true", "yes", "y", "on"}


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


def normalize_ai_mode(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return BACKWARD_COMPATIBLE_AI_MODE_ALIASES.get(normalized, normalized)


def validate_ai_mode(value: Any) -> str:
    ai_mode = normalize_ai_mode(value)

    if ai_mode not in VALID_AI_MODES:
        valid_modes = ", ".join(sorted(VALID_AI_MODES))
        raise ValueError(
            f"Invalid AI mode: {value or '[empty]'}. Use one of: {valid_modes}."
        )

    return ai_mode


def _portal_default_ai_mode() -> str:
    configured = normalize_ai_mode(
        os.getenv("PORTAL_DEFAULT_AI_MODE", PORTAL_DEFAULT_AI_MODE)
    )

    if configured in VALID_AI_MODES:
        return configured

    logger.warning(
        "Invalid PORTAL_DEFAULT_AI_MODE=%s; falling back to %s.",
        configured,
        PORTAL_DEFAULT_AI_MODE,
    )
    return PORTAL_DEFAULT_AI_MODE


def get_telegram_ai_mode() -> str:
    return validate_ai_mode(
        os.getenv("TELEGRAM_AI_MODE", TELEGRAM_DEFAULT_AI_MODE)
    )


def get_portal_ai_mode_from_headers(headers: Any) -> dict[str, Any]:
    requested_ai_mode = ""

    if headers is not None:
        requested_ai_mode = str(headers.get("X-AI-Mode") or "").strip()

    if not requested_ai_mode:
        requested_ai_mode = _portal_default_ai_mode()

    return build_ai_context(
        source_channel="portal",
        ai_mode=validate_ai_mode(requested_ai_mode),
    )


def get_non_portal_ai_mode() -> str | None:
    configured = (
        os.getenv("NON_PORTAL_AI_MODE")
        or os.getenv("TELEGRAM_AI_MODE")
        or os.getenv("PORTAL_DEFAULT_AI_MODE")
        or ""
    ).strip()

    if not configured:
        return None

    return validate_ai_mode(configured)


def build_ai_context(source_channel: str, ai_mode: Any) -> dict[str, Any]:
    resolved_ai_mode = validate_ai_mode(ai_mode)

    return {
        "ai_mode": resolved_ai_mode,
        "production_mode": resolved_ai_mode
        in {AI_MODE_PRODUCTION_HYBRID, AI_MODE_DEEPSEEK_ONLY},
        "local_ai_enabled": resolved_ai_mode
        in {AI_MODE_PRODUCTION_HYBRID, AI_MODE_TEST_LOCAL_ONLY},
        "deepseek_enabled": _deepseek_available(),
        "server_local_ai_enabled": _local_ai_available(),
        "source": source_channel,
        "source_channel": source_channel,
    }
