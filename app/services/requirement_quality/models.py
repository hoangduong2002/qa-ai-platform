from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QualitySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class QualityGateMode(str, Enum):
    OFF = "off"
    WARN = "warn"
    BLOCK_ON_CRITICAL = "block_on_critical"


class QualityIssueType(str, Enum):
    COMPLETENESS = "COMPLETENESS"
    CLARITY = "CLARITY"
    CONSISTENCY = "CONSISTENCY"
    TESTABILITY = "TESTABILITY"
    EXPECTED_RESULT_DEFINITION = "EXPECTED_RESULT_DEFINITION"
    DATA_DEFINITION = "DATA_DEFINITION"
    BOUNDARY_DEFINITION = "BOUNDARY_DEFINITION"
    PERMISSIONS = "PERMISSIONS"
    STATE_TRANSITIONS = "STATE_TRANSITIONS"
    INTEGRATION_BEHAVIOR = "INTEGRATION_BEHAVIOR"
    ERROR_HANDLING = "ERROR_HANDLING"
    NON_FUNCTIONAL_EXPECTATIONS = "NON_FUNCTIONAL_EXPECTATIONS"
    SCOPE_CLARITY = "SCOPE_CLARITY"
    CONTRADICTION = "CONTRADICTION"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"


class SourceReference(BaseModel):
    source_type: str = "jira"
    source_classification: str = "UNKNOWN"
    source_identifier: str | None = None
    source_location: str | None = None
    source_excerpt: str | None = None
    confidence: float = 0.0
    classification: str = "EXPLICIT"

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class QualityIssue(BaseModel):
    issue_id: str
    issue_type: QualityIssueType
    severity: QualitySeverity
    affected_field: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    proposed_question: str
    kb_retrieval_could_help: bool = False
    human_confirmation_mandatory: bool = True


class SuggestedClarificationQuestion(BaseModel):
    question_id: str
    issue_id: str
    question: str
    affected_field: str
    severity: QualitySeverity
    source_references: list[SourceReference] = Field(default_factory=list)


class QualityGateOverride(BaseModel):
    overridden_by: str
    reason: str
    timestamp: str
    affected_issue_ids: list[str] = Field(default_factory=list)


class RequirementQualityReportV1(BaseModel):
    schema_version: Literal["1.0"]
    mode: QualityGateMode
    score: int
    ready_for_test_design: bool

    blocking_issues: list[QualityIssue] = Field(default_factory=list)
    warnings: list[QualityIssue] = Field(default_factory=list)
    ambiguities: list[QualityIssue] = Field(default_factory=list)
    contradictions: list[QualityIssue] = Field(default_factory=list)
    missing_information: list[QualityIssue] = Field(default_factory=list)

    suggested_clarification_questions: list[SuggestedClarificationQuestion] = Field(default_factory=list)

    retrieval_needs: dict = Field(default_factory=lambda: {
        "knowledge_base_retrieval_required": False,
        "notes": "Phase 3 does not retrieve Project Knowledge Base content.",
    })

    override: QualityGateOverride | None = None
    source_references: list[SourceReference] = Field(default_factory=list)


class StructuredAnalysisValidationError(ValueError):
    pass
