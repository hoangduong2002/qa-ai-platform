from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any

from knowledge.domain.models import (
    ChunkRecord,
    CollectionMetadata,
    DocumentMetadata,
    KnowledgeBaseMetadata,
    SearchRequest,
    SearchResponse,
)


class KnowledgeStorage(ABC):
    @abstractmethod
    def create_kb(self, kb: KnowledgeBaseMetadata) -> KnowledgeBaseMetadata:
        raise NotImplementedError

    @abstractmethod
    def get_kb(self, kb_id: str) -> KnowledgeBaseMetadata:
        raise NotImplementedError

    @abstractmethod
    def list_kbs(self) -> list[KnowledgeBaseMetadata]:
        raise NotImplementedError

    @abstractmethod
    def update_kb(self, kb_id: str, patch: dict[str, Any]) -> KnowledgeBaseMetadata:
        raise NotImplementedError

    @abstractmethod
    def create_collection(self, collection: CollectionMetadata) -> CollectionMetadata:
        raise NotImplementedError

    @abstractmethod
    def list_collections(self, kb_id: str) -> list[CollectionMetadata]:
        raise NotImplementedError

    @abstractmethod
    def update_collection(self, kb_id: str, collection_id: str, patch: dict[str, Any]) -> CollectionMetadata:
        raise NotImplementedError

    @abstractmethod
    def save_document(self, document: DocumentMetadata, raw_content: bytes, ext: str) -> DocumentMetadata:
        raise NotImplementedError

    @abstractmethod
    def get_document(self, kb_id: str, document_id: str) -> DocumentMetadata:
        raise NotImplementedError

    @abstractmethod
    def list_documents(self, kb_id: str, collection_id: str | None = None) -> list[DocumentMetadata]:
        raise NotImplementedError

    @abstractmethod
    def update_document(self, kb_id: str, document_id: str, patch: dict[str, Any]) -> DocumentMetadata:
        raise NotImplementedError

    @abstractmethod
    def save_preview(self, kb_id: str, document_id: str, preview: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_published_chunks(self, kb_id: str, document_id: str, version: int, chunks: list[ChunkRecord]) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_published_chunks(self, kb_id: str) -> list[ChunkRecord]:
        raise NotImplementedError

    @abstractmethod
    def append_audit_event(self, kb_id: str, event: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_audit_events(self, kb_id: str, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def acquire_write_lock(self, kb_id: str) -> AbstractContextManager[None]:
        raise NotImplementedError

    @abstractmethod
    def kb_health(self, kb_id: str) -> dict[str, Any]:
        raise NotImplementedError


class KnowledgeRetriever(ABC):
    @abstractmethod
    def verify_fts5(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def rebuild_index(self, kb_id: str, chunks: list[ChunkRecord]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search(self, kb_id: str, request: SearchRequest) -> SearchResponse:
        raise NotImplementedError


class DocumentParser(ABC):
    @abstractmethod
    def supports_extension(self, extension: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, content: str) -> list[str]:
        raise NotImplementedError


class KnowledgeAuditWriter(ABC):
    @abstractmethod
    def append(self, kb_id: str, event: dict[str, Any]) -> str:
        raise NotImplementedError
