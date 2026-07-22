from __future__ import annotations

import os

from app.services.coverage_model.errors import CoverageModelConfigurationError
from app.services.coverage_model.models import CoverageModelMode


def coverage_model_mode() -> CoverageModelMode:
    configured_mode = os.getenv("COVERAGE_MODEL_MODE")

    if configured_mode is not None:
        raw = configured_mode.strip().lower()

        try:
            return CoverageModelMode(raw)
        except ValueError as error:
            allowed = ", ".join(item.value for item in CoverageModelMode)
            raise CoverageModelConfigurationError(
                f"Invalid COVERAGE_MODEL_MODE={configured_mode!r}. "
                f"Allowed values: {allowed}."
            ) from error

    # Backward-compatible mapping for the partial Phase 7 flag.
    raw = os.getenv("COVERAGE_MODEL_ENABLED", "off").strip().lower()

    if raw in {"enabled", "on", "true", "1"}:
        return CoverageModelMode.ENABLED

    if raw == CoverageModelMode.SHADOW.value:
        return CoverageModelMode.SHADOW

    if raw in {"off", "false", "0", ""}:
        return CoverageModelMode.OFF

    raise CoverageModelConfigurationError(
        f"Invalid legacy COVERAGE_MODEL_ENABLED={raw!r}. "
        "Use COVERAGE_MODEL_MODE=off, shadow, or enabled."
    )
