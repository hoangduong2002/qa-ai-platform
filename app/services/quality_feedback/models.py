from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class FeedbackAction(str, Enum):
    ACCEPTED_WITHOUT_EDIT = "ACCEPTED_WITHOUT_EDIT"
    ACCEPTED_WITH_EDIT = "ACCEPTED_WITH_EDIT"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    IRRELEVANT = "IRRELEVANT"
    MISSING_COVERAGE = "MISSING_COVERAGE"
    INCORRECT_EXPECTED_RESULT = "INCORRECT_EXPECTED_RESULT"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"
    OUTDATED_KNOWLEDGE = "OUTDATED_KNOWLEDGE"
    INCORRECT_REFERENCE = "INCORRECT_REFERENCE"
    UNCLEAR_STEP = "UNCLEAR_STEP"
    MISSING_TEST_DATA = "MISSING_TEST_DATA"


class FeedbackReason(str, Enum):
    DUPLICATE = "DUPLICATE"
    IRRELEVANT = "IRRELEVANT"
    MISSING_COVERAGE = "MISSING_COVERAGE"
    INCORRECT_EXPECTED_RESULT = "INCORRECT_EXPECTED_RESULT"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"
    OUTDATED_KNOWLEDGE = "OUTDATED_KNOWLEDGE"
    INCORRECT_REFERENCE = "INCORRECT_REFERENCE"
    UNCLEAR_STEP = "UNCLEAR_STEP"
    MISSING_TEST_DATA = "MISSING_TEST_DATA"
    OTHER = "OTHER"


class VersionMetadata(BaseModel):
    dataset_version: str = ""
    analyzer_version: str = ""
    generator_version: str = ""
    reviewer_version: str = ""
    retrieval_version: str = ""
    ranking_version: str = ""
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_identifiers: list[str] = Field(default_factory=list)
    model_configuration: dict[str, Any] = Field(default_factory=dict)


class FeedbackEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str
    ticket_id: str
    test_case_id: str
    testcase_version: str
    action: FeedbackAction
    reason_codes: list[FeedbackReason] = Field(default_factory=list)
    user: str
    timestamp: str
    original_content_hash: str
    edited_content_hash: str | None = None
    comment: str | None = None
    versions: VersionMetadata
    domain: str = "unspecified"
    durations_seconds: dict[str, float] = Field(default_factory=dict)
    estimated_qa_correction_minutes: float | None = Field(default=None, ge=0)

    @field_validator("ticket_id", "test_case_id", "user")
    @classmethod
    def required_text(cls, value: str) -> str:
        clean = " ".join((value or "").split())
        if not clean:
            raise ValueError("value is required")
        return clean

    @model_validator(mode="after")
    def edit_hash_is_consistent(self):
        if self.action == FeedbackAction.ACCEPTED_WITH_EDIT:
            if not self.edited_content_hash:
                raise ValueError("accepted-with-edit feedback requires edited content")
            if self.edited_content_hash == self.original_content_hash:
                raise ValueError("edited content must differ from original content")
        elif self.edited_content_hash:
            raise ValueError("edited content is only valid for ACCEPTED_WITH_EDIT")
        return self


class FeedbackSummary(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: str
    event_count: int
    action_counts: dict[str, int]
    reason_counts: dict[str, int]
    metrics: dict[str, dict[str, Any]]
    version_breakdown: dict[str, dict[str, int]]
    model_identifiers: list[str]
    model_configurations: list[dict[str, Any]]
    domain_breakdown: dict[str, int]
