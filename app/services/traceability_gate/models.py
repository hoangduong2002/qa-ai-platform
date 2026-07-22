from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TraceNodeType(str, Enum):
    JIRA_SOURCE_SECTION = "JIRA_SOURCE_SECTION"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    BUSINESS_RULE = "BUSINESS_RULE"
    KNOWLEDGE_REFERENCE = "KNOWLEDGE_REFERENCE"
    COVERAGE_CONDITION = "COVERAGE_CONDITION"
    SCENARIO = "SCENARIO"
    TEST_CASE = "TEST_CASE"
    EXPECTED_RESULT = "EXPECTED_RESULT"


class TraceabilityNode(BaseModel):
    node_id: str
    node_type: TraceNodeType
    object_id: str
    label: str
    metadata: dict = Field(default_factory=dict)


class TraceabilityEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relationship: str


class TraceabilityIssue(BaseModel):
    blocker_id: str
    category: str
    severity: str = "BLOCKER"
    object_id: str | None = None
    explanation: str


class TraceabilityArtifactV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    selected_testcase_version: str
    generated_at: str
    nodes: list[TraceabilityNode] = Field(default_factory=list)
    edges: list[TraceabilityEdge] = Field(default_factory=list)
    validation_issues: list[TraceabilityIssue] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class ExportGateStatus(str, Enum):
    ALLOWED = "ALLOWED"
    ALLOWED_WITH_WARNINGS = "ALLOWED_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    OVERRIDDEN = "OVERRIDDEN"


class ExportBlocker(BaseModel):
    blocker_id: str
    category: str
    explanation: str
    source: str
    object_id: str | None = None
    configured_to_block: bool = True


class ExportDecisionV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    testcase_version: str
    export_format: str
    status: ExportGateStatus
    gate_enabled: bool
    gate_mode: str
    blockers: list[ExportBlocker] = Field(default_factory=list)
    warnings: list[ExportBlocker] = Field(default_factory=list)
    uncovered_requirements: list[str] = Field(default_factory=list)
    unsupported_results: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    approval_status: dict = Field(default_factory=dict)
    override: dict | None = None
    traceability_summary: dict = Field(default_factory=dict)


class ExportOverrideV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    override_id: str
    ticket_id: str
    reason: str
    user_identity: str
    timestamp: str
    affected_blocker_ids: list[str]
    scope: str
