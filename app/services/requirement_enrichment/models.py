from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EnrichmentMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    MANUAL = "manual"
    AUTOMATIC = "automatic"


class EnrichedFactClassification(str, Enum):
    JIRA_FACT = "JIRA_FACT"
    KB_REFERENCE = "KB_REFERENCE"
    QA_CONFIRMED = "QA_CONFIRMED"
    ASSUMPTION = "ASSUMPTION"


class EnrichedSourceReference(BaseModel):
    source_type: str
    source_identifier: str | None = None
    source_location: str | None = None
    citation: str | None = None
    source_excerpt: str | None = None
    reviewed_decision: str | None = None


class EnrichedFact(BaseModel):
    statement: str
    classification: EnrichedFactClassification
    source_references: list[EnrichedSourceReference] = Field(default_factory=list)
    confidence: float = 0.0
    effective_date: str | None = None
    affected_requirement_fields: list[str] = Field(default_factory=list)

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        clean = (value or "").strip()
        if not clean:
            raise ValueError("statement is required")
        return clean

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class EnrichmentQuestion(BaseModel):
    question: str
    source: str = "quality_gate"
    related_issue_id: str | None = None


class EnrichmentConflict(BaseModel):
    conflict_id: str
    conflict_type: str
    severity: str
    jira_source: str | None = None
    kb_source: str | None = None
    recommended_action: str | None = None


class EnrichmentApproval(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    approved: bool = False
    approved_by: str = ""
    approved_at: str = ""
    note: str = ""


class EnrichedAnalysisReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: EnrichmentMode
    active_for_downstream: bool

    jira_derived_facts: list[EnrichedFact] = Field(default_factory=list)
    knowledge_supported_facts: list[EnrichedFact] = Field(default_factory=list)
    qa_confirmed_facts: list[EnrichedFact] = Field(default_factory=list)
    unresolved_questions: list[EnrichmentQuestion] = Field(default_factory=list)
    conflicts: list[EnrichmentConflict] = Field(default_factory=list)
    assumptions: list[EnrichedFact] = Field(default_factory=list)
    rejected_candidate_facts: list[EnrichedFact] = Field(default_factory=list)

    evaluation_metrics: dict = Field(default_factory=dict)
