from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    PARSING = "PARSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    PUBLISHING = "PUBLISHING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class KnowledgeBaseMetadata(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    jira_project_keys: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str


class KnowledgeBaseDeletionImpact(BaseModel):
    kb_id: str
    name: str
    collection_count: int
    document_count: int
    jira_project_keys: list[str] = Field(default_factory=list)
    historical_snapshot_count: int = 0
    historical_snapshots_preserved: bool = True
    active_operations: int = 0
    can_delete: bool = True
    blocking_reasons: list[str] = Field(default_factory=list)


class KnowledgeBaseDeletionResult(BaseModel):
    status: str = "deleted"
    deleted: bool = True
    kb_id: str
    name: str
    deleted_collection_count: int
    deleted_document_count: int
    released_jira_project_keys: list[str] = Field(default_factory=list)
    historical_snapshot_count: int = 0
    historical_snapshots_preserved: bool = True
    deleted_at: str
    deleted_by: str


class CollectionMetadata(BaseModel):
    kb_id: str
    collection_id: str
    name: str
    description: str = ""
    priority: int = 100
    archived: bool = False
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str


class DocumentMetadata(BaseModel):
    kb_id: str
    collection_id: str
    document_id: str
    title: str
    status: DocumentStatus
    version: int = 1
    checksum: str
    effective_from: str | None = None
    effective_to: str | None = None
    confidence: float = 1.0
    source_type: str
    external_id: str | None = None
    supersedes_document_id: str | None = None
    superseded_by_document_id: str | None = None
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    last_error: str = ""
    parsing_preview: dict[str, Any] = Field(default_factory=dict)
    publish_history: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class ChunkRecord(BaseModel):
    kb_id: str
    collection_id: str
    document_id: str
    version: int
    chunk_index: int
    content: str
    confidence: float
    effective_from: str | None = None
    effective_to: str | None = None
    checksum: str
    source_citation: str
    is_active: bool = True


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    collection_id: str | None = None
    document_id: str | None = None
    min_confidence: float | None = None
    effective_at: str | None = None
    active_only: bool = True
    explain: bool = True
    prefix: bool = False


class SearchResult(BaseModel):
    kb_id: str
    collection_id: str
    document_id: str
    version: int
    chunk_index: int
    content: str
    confidence: float
    score: float
    explanation: str
    source_citation: str


class SearchResponse(BaseModel):
    query: str
    took_ms: int
    total: int
    results: list[SearchResult]


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
