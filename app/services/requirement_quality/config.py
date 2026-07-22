from __future__ import annotations

import os

from app.services.requirement_quality.models import QualityGateMode


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def quality_gate_enabled() -> bool:
    return _env_bool("REQUIREMENT_QUALITY_GATE_ENABLED", False)


def quality_gate_mode() -> QualityGateMode:
    value = os.getenv("REQUIREMENT_QUALITY_GATE_MODE", "off").strip().lower()

    if value == QualityGateMode.WARN.value:
        return QualityGateMode.WARN
    if value == QualityGateMode.BLOCK_ON_CRITICAL.value:
        return QualityGateMode.BLOCK_ON_CRITICAL
    return QualityGateMode.OFF


def llm_review_enabled() -> bool:
    return _env_bool("REQUIREMENT_QUALITY_LLM_REVIEW_ENABLED", False)
