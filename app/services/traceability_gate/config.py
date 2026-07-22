from __future__ import annotations

import os
from enum import Enum


class ExportQualityGateMode(str, Enum):
    WARN = "warn"
    BLOCK = "block"


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def traceability_gate_enabled() -> bool:
    return _bool("TRACEABILITY_GATE_ENABLED", False)


def export_quality_gate_enabled() -> bool:
    return _bool("EXPORT_QUALITY_GATE_ENABLED", False)


def export_quality_gate_mode() -> ExportQualityGateMode:
    raw = os.getenv("EXPORT_QUALITY_GATE_MODE", ExportQualityGateMode.WARN.value).strip().lower()
    try:
        return ExportQualityGateMode(raw)
    except ValueError as error:
        raise ValueError(
            "EXPORT_QUALITY_GATE_MODE must be warn or block"
        ) from error


BLOCK_RULE_ENV = {
    "UNRESOLVED_BLOCKER": "EXPORT_GATE_BLOCK_UNRESOLVED_BLOCKERS",
    "UNCOVERED_ACCEPTANCE_CRITERION": "EXPORT_GATE_BLOCK_UNCOVERED_ACCEPTANCE_CRITERIA",
    "UNCOVERED_MANDATORY_COVERAGE": "EXPORT_GATE_BLOCK_UNCOVERED_MANDATORY_COVERAGE",
    "UNSUPPORTED_EXPECTED_RESULT": "EXPORT_GATE_BLOCK_UNSUPPORTED_EXPECTED_RESULTS",
    "UNREVIEWED_CONFLICT": "EXPORT_GATE_BLOCK_UNREVIEWED_CONFLICTS",
    "MISSING_TESTCASE_TRACEABILITY": "EXPORT_GATE_BLOCK_MISSING_TRACEABILITY",
    "MISSING_QA_APPROVAL": "EXPORT_GATE_BLOCK_MISSING_QA_APPROVAL",
}


def blocking_rule_enabled(category: str) -> bool:
    env_name = BLOCK_RULE_ENV.get(category)
    return _bool(env_name, True) if env_name else False


def authorized_qa_leads() -> set[str]:
    raw = os.getenv("EXPORT_GATE_QA_LEAD_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}
