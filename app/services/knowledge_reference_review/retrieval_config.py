from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def knowledge_retrieval_enabled() -> bool:
    # Default true preserves the pre-flag manual retrieval behavior. Clean
    # installations use the explicit false value in .env.qa.example.
    return _env_bool("KNOWLEDGE_RETRIEVAL_ENABLED", True)


def knowledge_retrieval_shadow_mode() -> bool:
    return _env_bool("KNOWLEDGE_RETRIEVAL_SHADOW_MODE", False)
