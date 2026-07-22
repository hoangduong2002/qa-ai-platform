from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceAuthority(str, Enum):
    CURRENT_JIRA_TICKET = "CURRENT_JIRA_TICKET"
    CONFIRMED_JIRA_COMMENTS_OR_CLARIFICATIONS = "CONFIRMED_JIRA_COMMENTS_OR_CLARIFICATIONS"
    OFFICIAL_ACTIVE_BUSINESS_RULES = "OFFICIAL_ACTIVE_BUSINESS_RULES"
    API_AND_INTEGRATION_SPECIFICATIONS = "API_AND_INTEGRATION_SPECIFICATIONS"
    EXISTING_TEST_CASES = "EXISTING_TEST_CASES"
    HISTORICAL_DEFECTS = "HISTORICAL_DEFECTS"
    OBSERVED_CURRENT_BEHAVIOR = "OBSERVED_CURRENT_BEHAVIOR"
    UNKNOWN = "UNKNOWN"


class ReferenceClassification(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OUTDATED = "OUTDATED"
    CONFLICT = "CONFLICT"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    HISTORICAL_CONTEXT_ONLY = "HISTORICAL_CONTEXT_ONLY"


class RequestedDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    MARK_OUTDATED = "MARK_OUTDATED"
    MARK_HISTORICAL = "MARK_HISTORICAL"


class ConflictType(str, Enum):
    CONTRADICTS_JIRA = "CONTRADICTS_JIRA"
    DATE_MISMATCH = "DATE_MISMATCH"
    VALUE_MISMATCH = "VALUE_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    OUTDATED_REFERENCE = "OUTDATED_REFERENCE"
    DUPLICATE_RULE = "DUPLICATE_RULE"
    UNSUPPORTED_BEHAVIOR = "UNSUPPORTED_BEHAVIOR"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"


class ConflictSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class JiraStatement(BaseModel):
    statement_id: str
    source: str
    text: str


class CandidateReference(BaseModel):
    result_id: str
    retrieval_need: str
    jira_issue_being_clarified: str
    kb_id: str
    collection_id: str
    document_id: str
    version: int
    chunk_index: int
    excerpt: str
    citation: str
    confidence: float
    effective_from: str | None = None
    effective_to: str | None = None
    source_type: str = "UNKNOWN"
    status: str = "INDEXED"
    intended_use: str = "analysis"

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class DetectedConflict(BaseModel):
    conflict_id: str
    source_result_id: str
    jira_statement: str
    jira_source: str
    kb_statement: str
    kb_source: str
    conflict_type: ConflictType
    severity: ConflictSeverity
    authoritative_source: SourceAuthority
    recommended_action: str
    human_confirmation_required: bool = True


class ReviewedReference(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    source_result_id: str
    classification: ReferenceClassification
    requested_decision: RequestedDecision
    reviewed_by: str
    reviewed_at: str
    review_note: str = ""
    decision_reason: str

    retrieval_need: str
    jira_issue_being_clarified: str

    kb_id: str
    collection_id: str
    document_id: str
    version: int
    chunk_index: int
    excerpt: str
    citation: str
    confidence: float
    effective_from: str | None = None
    effective_to: str | None = None
    source_type: str = "UNKNOWN"
    status: str = "INDEXED"
    intended_use: str = "analysis"

    conflicts: list[DetectedConflict] = Field(default_factory=list)


class AuthorityPolicy(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ordered_authorities: list[SourceAuthority]


class ReviewRequest(BaseModel):
    request_id: str
    ticket_id: str
    retrieval_need: str
    jira_issue_being_clarified: str
    query: str
    kb_id: str
    created_at: str
    created_by: str
    status: str = "OPEN"
    result_ids: list[str] = Field(default_factory=list)
