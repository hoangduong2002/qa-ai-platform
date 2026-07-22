from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.services.test_case_generator_v2.models import (
    GeneratorSourceReference,
    TestCaseSetV2,
)


class ReviewSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class ReviewStatus(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_WARNINGS = "APPROVED_WITH_WARNINGS"
    NEEDS_QA_REVIEW = "NEEDS_QA_REVIEW"


class ReviewCategory(str, Enum):
    UNSUPPORTED_EXPECTED_RESULT = "UNSUPPORTED_EXPECTED_RESULT"
    INVENTED_AMOUNT = "INVENTED_AMOUNT"
    INVENTED_STATUS = "INVENTED_STATUS"
    INVENTED_MESSAGE = "INVENTED_MESSAGE"
    INVENTED_CALCULATION = "INVENTED_CALCULATION"
    KB_CONTRADICTION_WITH_JIRA = "KB_CONTRADICTION_WITH_JIRA"
    MISSING_SOURCE_REFERENCE = "MISSING_SOURCE_REFERENCE"
    UNCOVERED_ACCEPTANCE_CRITERION = "UNCOVERED_ACCEPTANCE_CRITERION"
    UNCOVERED_BUSINESS_RULE = "UNCOVERED_BUSINESS_RULE"
    UNCOVERED_BLOCKING_CONDITION = "UNCOVERED_BLOCKING_CONDITION"
    UNHANDLED_CLARIFICATION = "UNHANDLED_CLARIFICATION"
    MISSING_POSITIVE_PATH = "MISSING_POSITIVE_PATH"
    MISSING_NEGATIVE_PATH = "MISSING_NEGATIVE_PATH"
    MISSING_BOUNDARY = "MISSING_BOUNDARY"
    MISSING_PERMISSION_CASE = "MISSING_PERMISSION_CASE"
    MISSING_STATE_TRANSITION = "MISSING_STATE_TRANSITION"
    MISSING_INTEGRATION_FAILURE = "MISSING_INTEGRATION_FAILURE"
    MISSING_REGRESSION_CASE = "MISSING_REGRESSION_CASE"
    MISSING_ID = "MISSING_ID"
    MISSING_TITLE = "MISSING_TITLE"
    EMPTY_STEPS = "EMPTY_STEPS"
    EMPTY_EXPECTED_RESULTS = "EMPTY_EXPECTED_RESULTS"
    MISSING_TRACEABILITY = "MISSING_TRACEABILITY"
    DUPLICATE_ID = "DUPLICATE_ID"
    DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    UNRESOLVED_ASSUMPTION = "UNRESOLVED_ASSUMPTION"
    INVALID_SOURCE_REFERENCE = "INVALID_SOURCE_REFERENCE"
    UNCOVERED_MANDATORY_CONDITION = "UNCOVERED_MANDATORY_CONDITION"
    VAGUE_TITLE = "VAGUE_TITLE"
    INVALID_PRECONDITION = "INVALID_PRECONDITION"
    MULTIPLE_ACTIONS = "MULTIPLE_ACTIONS"
    UNOBSERVABLE_EXPECTED_RESULT = "UNOBSERVABLE_EXPECTED_RESULT"
    MISSING_TEST_DATA = "MISSING_TEST_DATA"
    CONTRADICTORY_STEPS = "CONTRADICTORY_STEPS"
    OUT_OF_SCOPE_CASE = "OUT_OF_SCOPE_CASE"
    NON_EXECUTABLE_CASE = "NON_EXECUTABLE_CASE"
    REVIEWER_FAILURE = "REVIEWER_FAILURE"
    CORRECTION_FAILURE = "CORRECTION_FAILURE"


class TestQualityIssue(BaseModel):
    issue_id: str
    severity: ReviewSeverity
    category: ReviewCategory
    test_case_id: str | None = None
    source_refs: list[GeneratorSourceReference] = Field(default_factory=list)
    explanation: str
    recommended_correction: str
    auto_correctable: bool = False
    blocks_export: bool = False
    detected_by: str = "deterministic"


class MissingCoverageItem(BaseModel):
    coverage_id: str
    coverage_type: str
    explanation: str
    source_refs: list[GeneratorSourceReference] = Field(default_factory=list)


class DuplicateGroup(BaseModel):
    group_id: str
    test_case_ids: list[str]
    similarity: float = Field(ge=0, le=1)
    reason: str


class TestQualityReportV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    review_status: ReviewStatus
    summary: str
    issues: list[TestQualityIssue] = Field(default_factory=list)
    missing_coverage: list[MissingCoverageItem] = Field(default_factory=list)
    duplicate_groups: list[DuplicateGroup] = Field(default_factory=list)
    correction_instructions: list[str] = Field(default_factory=list)
    reviewer_version: str = "phase9-v1"
    model_metadata: dict = Field(default_factory=dict)
    review_attempts: int = 1
    evaluation_metrics: dict = Field(default_factory=dict)


class CorrectionChange(BaseModel):
    test_case_id: str
    issue_ids: list[str] = Field(default_factory=list)
    fields_changed: list[str] = Field(default_factory=list)
    description: str


class CorrectionResult(BaseModel):
    corrected_testcases: TestCaseSetV2
    changes: list[CorrectionChange] = Field(default_factory=list)


class CorrectionAttempt(BaseModel):
    attempt: int
    status: str
    affected_test_case_ids: list[str] = Field(default_factory=list)
    changes: list[CorrectionChange] = Field(default_factory=list)
    error: str = ""
    model_metadata: dict = Field(default_factory=dict)


class CorrectionHistoryV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    max_review_attempts: int = 2
    review_attempts: int = 1
    correction_attempts: list[CorrectionAttempt] = Field(default_factory=list)
