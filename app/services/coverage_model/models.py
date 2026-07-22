from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class CoverageModelMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ENABLED = "enabled"


class CoverageConditionType(str, Enum):
    MANDATORY = "MANDATORY"
    BOUNDARY = "BOUNDARY"
    NEGATIVE = "NEGATIVE"
    INTEGRATION = "INTEGRATION"
    STATE_TRANSITION = "STATE_TRANSITION"
    PERMISSION = "PERMISSION"
    REGRESSION_RISK = "REGRESSION_RISK"


class RiskPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CoverageSourceReference(BaseModel):
    source_type: str
    source_identifier: str | None = None
    source_location: str | None = None
    citation: str | None = None
    source_excerpt: str | None = None


class CoverageDimensionValue(BaseModel):
    value_id: str
    value: str
    risk_priority: RiskPriority = RiskPriority.MEDIUM
    rationale: str = ""
    source_refs: list[CoverageSourceReference] = Field(default_factory=list)


class CoverageDimension(BaseModel):
    dimension_id: str
    name: str
    values: list[CoverageDimensionValue] = Field(default_factory=list)
    suggested_by_profile: bool = False
    rationale: str = ""
    source_refs: list[CoverageSourceReference] = Field(default_factory=list)


class CoverageCondition(BaseModel):
    condition_id: str
    condition_type: CoverageConditionType
    title: str
    dimension_value_refs: dict[str, str] = Field(default_factory=dict)
    mandatory: bool = False
    risk_priority: RiskPriority = RiskPriority.MEDIUM
    rationale: str = ""
    source_refs: list[CoverageSourceReference] = Field(default_factory=list)


class CoverageCombination(BaseModel):
    combination_id: str
    dimension_value_refs: dict[str, str] = Field(default_factory=dict)
    reason: str
    rationale: str = ""
    source_refs: list[CoverageSourceReference] = Field(default_factory=list)


class CoverageModelV1(BaseModel):
    version: Literal["1.0"] = "1.0"
    coverage_model_id: str
    ticket_id: str
    requirement_refs: list[str] = Field(default_factory=list)
    dimensions: list[CoverageDimension] = Field(default_factory=list)
    coverage_conditions: list[CoverageCondition] = Field(default_factory=list)
    excluded_combinations: list[CoverageCombination] = Field(default_factory=list)
    out_of_scope_combinations: list[CoverageCombination] = Field(default_factory=list)
    risk_summary: dict = Field(default_factory=dict)
    uncovered_questions: list[str] = Field(default_factory=list)
    source_refs: list[CoverageSourceReference] = Field(default_factory=list)
    evaluation_metrics: dict = Field(default_factory=dict)
    generation_metadata: dict = Field(default_factory=dict)
