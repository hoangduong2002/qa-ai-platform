import os

from app.config.env_loader import load_project_env


load_project_env()

TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)

    if not value:
        return default

    return value.lower() in TRUE_VALUES


def force_disable_local_ai() -> bool:
    return _env_bool("FORCE_DISABLE_LOCAL_AI", False)


def get_local_ai_provider() -> str:
    return _env_str("LOCAL_AI_PROVIDER", "OLLAMA").upper() or "OLLAMA"


def get_LOCAL_base_url() -> str:
    return _env_str("LOCAL_BASE_URL").rstrip("/")


def is_local_ai_enabled() -> bool:
    return bool(get_LOCAL_base_url()) and not force_disable_local_ai()


def is_local_vision_enabled() -> bool:
    return is_local_ai_enabled()


def is_local_compact_enabled() -> bool:
    return is_local_ai_enabled()


def is_local_text_fallback_enabled() -> bool:
    return is_local_ai_enabled()


def get_LOCAL_vision_model() -> str:
    return _env_str("LOCAL_VISION_MODEL", "qwen2.5vl:7b")


def get_LOCAL_compact_model() -> str:
    return (
        _env_str("LOCAL_COMPACT_MODEL")
        or get_LOCAL_text_model()
    )


def get_LOCAL_text_model() -> str:
    return _env_str("LOCAL_TEXT_MODEL", "qwen2.5:14b")
