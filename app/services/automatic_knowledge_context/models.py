from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeRetrievalStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    DISABLED = "disabled"
    RETRIEVAL_DISABLED = "retrieval_disabled"
    NO_PROJECT_KEY = "no_project_key"
    NO_MAPPING = "no_mapping"
    KB_NOT_READY = "kb_not_ready"
    NO_MATCHES = "no_matches"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class KnowledgeQuery(BaseModel):
    category: str
    query: str
    collection_id: str | None = None


class KnowledgeSnapshotReference(BaseModel):
    reference_id: str
    source_result_id: str
    kb_id: str
    collection_id: str
    document_id: str
    document_version: int
    chunk_index: int
    content_hash: str
    excerpt: str
    title: str
    citation: str
    score: float
    confidence: float
    authority: str
    authority_heuristic: bool = True
    source_type: str = "UNKNOWN"
    matched_query_categories: list[str] = Field(default_factory=list)
    selected: bool = False
    used_in_prompt: bool = False


class KnowledgeRetrievalSnapshot(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: str
    ticket_id: str
    analysis_run_id: str
    jira_issue_key: str | None = None
    jira_project_key: str | None = None
    knowledge_base_id: str | None = None
    knowledge_base_name: str | None = None
    status: KnowledgeRetrievalStatus
    status_message: str
    created_at: str
    elapsed_ms: int = 0
    queries: list[KnowledgeQuery] = Field(default_factory=list)
    retrieved_count: int = 0
    selected_count: int = 0
    references: list[KnowledgeSnapshotReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    selection_mode: str = "automatic"
    based_on_snapshot_id: str | None = None
    adjusted_by: str | None = None
    adjusted_at: str | None = None
