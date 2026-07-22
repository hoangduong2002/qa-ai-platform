from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceClassification(str, Enum):
    JIRA_DESCRIPTION = "JIRA_DESCRIPTION"
    JIRA_ACCEPTANCE_CRITERIA = "JIRA_ACCEPTANCE_CRITERIA"
    JIRA_COMMENT = "JIRA_COMMENT"
    JIRA_ATTACHMENT = "JIRA_ATTACHMENT"
    UNKNOWN = "UNKNOWN"


class FactClassification(str, Enum):
    EXPLICIT = "EXPLICIT"
    IMPLIED = "IMPLIED"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTION = "CONTRADICTION"
    ASSUMPTION = "ASSUMPTION"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class SourceReference(BaseModel):
    source_type: str = "jira"
    source_classification: SourceClassification = SourceClassification.UNKNOWN
    source_identifier: str | None = None
    source_location: str | None = None
    source_excerpt: str | None = None
    confidence: float = 0.0
    classification: FactClassification = FactClassification.EXPLICIT

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class StructuredFact(BaseModel):
    fact_id: str | None = None
    text: str
    confidence: float = 0.0
    classification: FactClassification = FactClassification.EXPLICIT
    provenance: list[SourceReference] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("text is required")
        return value

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class StructuredRequirementAnalysisV1(BaseModel):
    schema_version: Literal["1.0"]

    business_goal: list[StructuredFact] = Field(default_factory=list)
    actors: list[StructuredFact] = Field(default_factory=list)
    preconditions: list[StructuredFact] = Field(default_factory=list)
    triggers: list[StructuredFact] = Field(default_factory=list)
    business_rules: list[StructuredFact] = Field(default_factory=list)
    input_data: list[StructuredFact] = Field(default_factory=list)
    expected_results: list[StructuredFact] = Field(default_factory=list)
    error_behaviors: list[StructuredFact] = Field(default_factory=list)
    state_transitions: list[StructuredFact] = Field(default_factory=list)
    permissions: list[StructuredFact] = Field(default_factory=list)
    integrations: list[StructuredFact] = Field(default_factory=list)
    non_functional_requirements: list[StructuredFact] = Field(default_factory=list)
    out_of_scope: list[StructuredFact] = Field(default_factory=list)
    ambiguities: list[StructuredFact] = Field(default_factory=list)
    contradictions: list[StructuredFact] = Field(default_factory=list)
    assumptions: list[StructuredFact] = Field(default_factory=list)
    missing_information: list[StructuredFact] = Field(default_factory=list)

    source_references: list[SourceReference] = Field(default_factory=list)


def validate_structured_requirement_analysis(payload: dict) -> StructuredRequirementAnalysisV1:
    return StructuredRequirementAnalysisV1.model_validate(payload)
