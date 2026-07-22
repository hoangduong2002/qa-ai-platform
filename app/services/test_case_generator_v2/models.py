from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TestCaseOrigin(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    BUSINESS_RULE = "BUSINESS_RULE"
    BOUNDARY_ANALYSIS = "BOUNDARY_ANALYSIS"
    ERROR_HANDLING = "ERROR_HANDLING"
    INTEGRATION = "INTEGRATION"
    PERMISSION = "PERMISSION"
    STATE_TRANSITION = "STATE_TRANSITION"
    HISTORICAL_DEFECT = "HISTORICAL_DEFECT"
    REGRESSION = "REGRESSION"
    SECURITY = "SECURITY"
    NON_FUNCTIONAL = "NON_FUNCTIONAL"


class TestCasePriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GeneratorSourceType(str, Enum):
    JIRA = "JIRA"
    CONFIRMED_CLARIFICATION = "CONFIRMED_CLARIFICATION"
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    HISTORICAL_DEFECT = "HISTORICAL_DEFECT"
    COVERAGE_MODEL = "COVERAGE_MODEL"
    SCENARIO = "SCENARIO"


class GeneratorSourceReference(BaseModel):
    source_type: GeneratorSourceType
    source_id: str
    citation: str | None = None
    excerpt: str | None = None
    classification: str | None = None

    @field_validator("source_id")
    @classmethod
    def source_id_required(cls, value: str) -> str:
        clean = " ".join((value or "").split())
        if not clean:
            raise ValueError("source_id is required")
        return clean

    def supports_expected_behavior(self) -> bool:
        if self.source_type in {
            GeneratorSourceType.JIRA,
            GeneratorSourceType.CONFIRMED_CLARIFICATION,
        }:
            return True
        return (
            self.source_type == GeneratorSourceType.KNOWLEDGE_BASE
            and str(self.classification or "").upper() == "ACCEPTED"
        )


class TestDataItem(BaseModel):
    name: str
    value: str
    source_refs: list[GeneratorSourceReference] = Field(default_factory=list)
    assumption: str | None = None
    unresolved_question: str | None = None

    @model_validator(mode="after")
    def value_has_support(self):
        if not self.value.strip():
            raise ValueError("test data value must be explicit")
        if not self.source_refs and not self.assumption and not self.unresolved_question:
            raise ValueError(
                "test data must have a source reference, assumption, or unresolved question"
            )
        return self


class TestStepV2(BaseModel):
    step_number: int = Field(ge=1)
    action: str

    @field_validator("action")
    @classmethod
    def primary_action_only(cls, value: str) -> str:
        clean = " ".join((value or "").split())
        if not clean:
            raise ValueError("step action is required")
        lowered = clean.casefold()
        if " and then " in lowered or "; then " in lowered:
            raise ValueError("each step must contain one primary action")
        return clean


class ExpectedResultV2(BaseModel):
    step_number: int = Field(ge=1)
    expected_result: str
    source_refs: list[GeneratorSourceReference] = Field(default_factory=list)
    assumption: str | None = None
    unresolved_question: str | None = None

    @model_validator(mode="after")
    def expected_behavior_is_supported(self):
        if not self.expected_result.strip():
            raise ValueError("expected_result is required")
        supported = any(ref.supports_expected_behavior() for ref in self.source_refs)
        if not supported and not self.assumption and not self.unresolved_question:
            raise ValueError(
                "expected result requires an authoritative/approved source or an explicit assumption/unresolved question"
            )
        return self


class TestCaseV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    test_case_id: str
    title: str
    objective: str
    preconditions: list[str] = Field(default_factory=list)
    test_data: list[TestDataItem]
    steps: list[TestStepV2]
    expected_results: list[ExpectedResultV2]
    postconditions: list[str] = Field(default_factory=list)
    priority: TestCasePriority
    test_type: str
    origin: TestCaseOrigin
    requirement_refs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    coverage_refs: list[str] = Field(default_factory=list)
    scenario_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    automation_candidate: bool
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_links(self):
        if not self.test_data:
            raise ValueError("test_data must contain at least one explicit item")
        if not self.steps:
            raise ValueError("steps must not be empty")
        if not self.expected_results:
            raise ValueError("expected_results must not be empty")
        step_numbers = {step.step_number for step in self.steps}
        if len(step_numbers) != len(self.steps):
            raise ValueError("step numbers must be unique")
        if any(result.step_number not in step_numbers for result in self.expected_results):
            raise ValueError("every expected result must link to an existing step")
        for result in self.expected_results:
            if result.assumption and result.assumption not in self.assumptions:
                raise ValueError("expected-result assumption must be listed in assumptions")
            if (
                result.unresolved_question
                and result.unresolved_question not in self.unresolved_questions
            ):
                raise ValueError(
                    "expected-result unresolved question must be listed in unresolved_questions"
                )
        if self.origin == TestCaseOrigin.HISTORICAL_DEFECT:
            source_refs = [
                ref
                for result in self.expected_results
                for ref in result.source_refs
            ]
            if source_refs and not any(ref.supports_expected_behavior() for ref in source_refs):
                if not self.assumptions and not self.unresolved_questions:
                    raise ValueError(
                        "historical defects cannot define expected behavior without confirmation"
                    )
        return self


class TestCaseSetV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    generator_version: Literal["v2"] = "v2"
    ticket_id: str
    test_cases: list[TestCaseV2]
    quality_blocked: bool = False
    quality_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [item.test_case_id for item in self.test_cases]
        if len(ids) != len(set(ids)):
            raise ValueError("test_case_id values must be unique")
        fingerprints = [
            (" ".join(item.title.casefold().split()), " ".join(item.objective.casefold().split()))
            for item in self.test_cases
        ]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("duplicate or near-duplicate test cases are not allowed")
        for index, left in enumerate(fingerprints):
            left_tokens = set(" ".join(left).split())
            for right in fingerprints[index + 1 :]:
                right_tokens = set(" ".join(right).split())
                union = left_tokens | right_tokens
                similarity = len(left_tokens & right_tokens) / len(union) if union else 1.0
                if similarity >= 0.9:
                    raise ValueError(
                        "duplicate or near-duplicate test cases are not allowed"
                    )
        return self
