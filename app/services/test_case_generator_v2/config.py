from __future__ import annotations

import os
from enum import Enum


class TestCaseGeneratorConfigurationError(ValueError):
    pass


class TestCaseGeneratorVersion(str, Enum):
    V1 = "v1"
    V2_SHADOW = "v2-shadow"
    V2_MANUAL = "v2-manual"
    V2 = "v2"


def test_case_generator_version() -> TestCaseGeneratorVersion:
    raw = os.getenv(
        "TEST_CASE_GENERATOR_VERSION",
        TestCaseGeneratorVersion.V1.value,
    ).strip().lower()

    try:
        return TestCaseGeneratorVersion(raw)
    except ValueError as error:
        allowed = ", ".join(item.value for item in TestCaseGeneratorVersion)
        raise TestCaseGeneratorConfigurationError(
            f"Invalid TEST_CASE_GENERATOR_VERSION={raw!r}. Allowed values: {allowed}."
        ) from error
