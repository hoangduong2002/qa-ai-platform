import os

from app.config.env_loader import load_project_env
from app.services.portal_ai_mode_service import is_local_ai_allowed_for_request


load_project_env()

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)

    if not value:
        return default

    normalized = value.lower()

    if normalized in TRUE_VALUES:
        return True

    if normalized in FALSE_VALUES:
        return False

    return default


def _env_bool_optional(name: str) -> bool | None:
    value = _env_str(name)

    if not value:
        return None

    normalized = value.lower()

    if normalized in TRUE_VALUES:
        return True

    if normalized in FALSE_VALUES:
        return False

    return None


def is_local_ai_enabled() -> bool:
    return _env_bool("LOCAL_AI_ENABLED", False) and is_local_ai_allowed_for_request()


def get_local_ai_provider() -> str:
    return _env_str("LOCAL_AI_PROVIDER", "LOCAL").upper() or "LOCAL"


def is_local_vision_enabled() -> bool:
    if not is_local_ai_enabled():
        return False

    return _env_bool("LOCAL_VISION_ENABLED", False)


def is_figma_local_vision_enabled() -> bool:
    if not is_local_ai_enabled():
        return False

    explicit = _env_bool_optional("FIGMA_LOCAL_VISION_ENABLED")

    if explicit is not None:
        return explicit

    return is_local_vision_enabled()


def is_attachment_local_vision_enabled() -> bool:
    if not is_local_ai_enabled():
        return False

    explicit = _env_bool_optional("ATTACHMENT_LOCAL_VISION_ENABLED")

    if explicit is not None:
        return explicit

    return is_local_vision_enabled()


def is_local_compact_enabled() -> bool:
    if not is_local_ai_enabled():
        return False

    return _env_bool("LOCAL_COMPACT_ENABLED", False)


def is_local_text_fallback_enabled() -> bool:
    if not is_local_ai_enabled():
        return False

    return _env_bool("LOCAL_TEXT_FALLBACK_ENABLED", False)


def get_LOCAL_base_url() -> str:
    return (
        _env_str("LOCAL_BASE_URL")
        or _env_str("LOCAL_VISION_BASE_URL")
        or "http://localhost:11434"
    ).rstrip("/")


def get_LOCAL_vision_model() -> str:
    return (
        _env_str("LOCAL_VISION_MODEL")
        or "qwen2.5vl:7b"
    )


def get_LOCAL_compact_model() -> str:
    return (
        _env_str("LOCAL_COMPACT_MODEL")
        or _env_str("COMPACT_LLM_MODEL")
        or "qwen2.5:14b"
    )


def get_LOCAL_text_model() -> str:
    return (
        _env_str("LOCAL_TEXT_MODEL")
        or "qwen2.5:14b"
    )
