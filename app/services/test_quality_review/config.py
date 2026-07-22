from __future__ import annotations

import os
from enum import Enum


class TestQualityReviewConfigurationError(ValueError):
    pass


class TestQualityReviewMode(str, Enum):
    OFF = "off"
    WARN = "warn"
    BLOCK_EXPORT = "block_export"


def _enabled() -> bool:
    return os.getenv("TEST_QUALITY_REVIEW_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "y", "on"
    }


def test_quality_review_mode() -> TestQualityReviewMode:
    if not _enabled():
        return TestQualityReviewMode.OFF
    raw = os.getenv("TEST_QUALITY_REVIEW_MODE", TestQualityReviewMode.WARN.value).strip().lower()
    try:
        return TestQualityReviewMode(raw)
    except ValueError as error:
        allowed = ", ".join(item.value for item in TestQualityReviewMode)
        raise TestQualityReviewConfigurationError(
            f"Invalid TEST_QUALITY_REVIEW_MODE={raw!r}. Allowed values: {allowed}."
        ) from error


def reviewer_ai_mode(default: str | None) -> str | None:
    return os.getenv("TEST_QUALITY_REVIEW_AI_MODE", "").strip() or default


def reviewer_model() -> str | None:
    return os.getenv("TEST_QUALITY_REVIEW_MODEL", "").strip() or None


def corrector_ai_mode(default: str | None) -> str | None:
    return os.getenv("TEST_QUALITY_CORRECTOR_AI_MODE", "").strip() or default


def corrector_model() -> str | None:
    return os.getenv("TEST_QUALITY_CORRECTOR_MODEL", "").strip() or None
