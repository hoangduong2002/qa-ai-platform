from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import jsonlines
from filelock import FileLock

from knowledge.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from knowledge.domain.models import (
    ChunkRecord,
    CollectionMetadata,
    DocumentMetadata,
    KnowledgeBaseMetadata,
)
from knowledge.domain.protocols import KnowledgeAuditWriter, KnowledgeStorage
from knowledge.storage.utils import (
    atomic_write_json,
    atomic_write_text,
    read_json,
    safe_child,
    validate_identifier,
)


class FileSystemKnowledgeStorage(KnowledgeStorage, KnowledgeAuditWriter):
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = self.root / "_config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        mappings = self.config_dir / "jira_project_mappings.json"
        if not mappings.exists():
            atomic_write_json(mappings, {})

    def _kb_dir(self, kb_id: str) -> Path:
        kb_id = validate_identifier(kb_id, "kb_id")
        return safe_child(self.root, kb_id)

    def _kb_meta_file(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / "knowledge_base.json"

    def _collections_dir(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / "collections"

    def _collection_file(self, kb_id: str, collection_id: str) -> Path:
        collection_id = validate_identifier(collection_id, "collection_id")
        return self._collections_dir(kb_id) / f"{collection_id}.json"

    def _documents_dir(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / "documents"

    def _document_dir(self, kb_id: str, document_id: str) -> Path:
        document_id = validate_identifier(document_id, "document_id")
        return safe_child(self._documents_dir(kb_id), document_id)

    def _document_file(self, kb_id: str, document_id: str) -> Path:
        return self._document_dir(kb_id, document_id) / "document.json"

    def _indexes_dir(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / "indexes"

    def _audit_jobs_dir(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / "audit" / "jobs"

    def _ensure_kb_layout(self, kb_id: str) -> None:
        kb_dir = self._kb_dir(kb_id)
        for path in [
            kb_dir,
            kb_dir / "collections",
            kb_dir / "documents",
            kb_dir / "indexes",
            kb_dir / "audit" / "jobs",
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def create_kb(self, kb: KnowledgeBaseMetadata) -> KnowledgeBaseMetadata:
        kb_id = validate_identifier(kb.kb_id, "kb_id")
        self._ensure_kb_layout(kb_id)
        meta_file = self._kb_meta_file(kb_id)

        if meta_file.exists():
            raise KnowledgeValidationError(f"Knowledge base already exists: {kb_id}")

        atomic_write_json(meta_file, kb.model_dump())
        return kb

    def get_kb(self, kb_id: str) -> KnowledgeBaseMetadata:
        meta_file = self._kb_meta_file(kb_id)

        if not meta_file.exists():
            raise KnowledgeNotFoundError(f"Knowledge base not found: {kb_id}")

        return KnowledgeBaseMetadata.model_validate(read_json(meta_file, {}))

    def list_kbs(self) -> list[KnowledgeBaseMetadata]:
        if not self.root.exists():
            return []

        items: list[KnowledgeBaseMetadata] = []

        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.name.startswith("_"):
                continue

            meta_file = path / "knowledge_base.json"
            if not meta_file.exists():
                continue

            items.append(KnowledgeBaseMetadata.model_validate(read_json(meta_file, {})))

        return items

    def update_kb(self, kb_id: str, patch: dict[str, Any]) -> KnowledgeBaseMetadata:
        kb = self.get_kb(kb_id)
        data = kb.model_dump()
        data.update(patch)
        updated = KnowledgeBaseMetadata.model_validate(data)
        atomic_write_json(self._kb_meta_file(kb_id), updated.model_dump())
        return updated

    def create_collection(self, collection: CollectionMetadata) -> CollectionMetadata:
        self._ensure_kb_layout(collection.kb_id)
        file_path = self._collection_file(collection.kb_id, collection.collection_id)

        if file_path.exists():
            raise KnowledgeValidationError(
                f"Collection already exists: {collection.collection_id}"
            )

        atomic_write_json(file_path, collection.model_dump())
        return collection

    def list_collections(self, kb_id: str) -> list[CollectionMetadata]:
        directory = self._collections_dir(kb_id)
        if not directory.exists():
            return []

        items: list[CollectionMetadata] = []

        for path in sorted(directory.glob("*.json")):
            items.append(CollectionMetadata.model_validate(read_json(path, {})))

        return items

    def update_collection(self, kb_id: str, collection_id: str, patch: dict[str, Any]) -> CollectionMetadata:
        file_path = self._collection_file(kb_id, collection_id)

        if not file_path.exists():
            raise KnowledgeNotFoundError(f"Collection not found: {collection_id}")

        current = CollectionMetadata.model_validate(read_json(file_path, {}))
        data = current.model_dump()
        data.update(patch)
        updated = CollectionMetadata.model_validate(data)
        atomic_write_json(file_path, updated.model_dump())
        return updated

    def save_document(self, document: DocumentMetadata, raw_content: bytes, ext: str) -> DocumentMetadata:
        self._ensure_kb_layout(document.kb_id)
        doc_dir = self._document_dir(document.kb_id, document.document_id)
        original_dir = doc_dir / "original"
        preview_dir = doc_dir / "preview"
        published_dir = doc_dir / "published"

        original_dir.mkdir(parents=True, exist_ok=True)
        preview_dir.mkdir(parents=True, exist_ok=True)
        published_dir.mkdir(parents=True, exist_ok=True)

        original_file = original_dir / f"v{document.version}{ext}"
        if not original_file.exists():
            original_file.write_bytes(raw_content)

        atomic_write_json(self._document_file(document.kb_id, document.document_id), document.model_dump())
        return document

    def get_document(self, kb_id: str, document_id: str) -> DocumentMetadata:
        file_path = self._document_file(kb_id, document_id)
        if not file_path.exists():
            raise KnowledgeNotFoundError(f"Document not found: {document_id}")
        return DocumentMetadata.model_validate(read_json(file_path, {}))

    def list_documents(self, kb_id: str, collection_id: str | None = None) -> list[DocumentMetadata]:
        directory = self._documents_dir(kb_id)
        if not directory.exists():
            return []

        items: list[DocumentMetadata] = []

        for doc_dir in sorted(directory.iterdir()):
            if not doc_dir.is_dir():
                continue

            file_path = doc_dir / "document.json"
            if not file_path.exists():
                continue

            item = DocumentMetadata.model_validate(read_json(file_path, {}))
            if collection_id and item.collection_id != collection_id:
                continue
            items.append(item)

        return items

    def update_document(self, kb_id: str, document_id: str, patch: dict[str, Any]) -> DocumentMetadata:
        current = self.get_document(kb_id, document_id)
        data = current.model_dump()
        data.update(patch)
        updated = DocumentMetadata.model_validate(data)
        atomic_write_json(self._document_file(kb_id, document_id), updated.model_dump())
        return updated

    def save_preview(self, kb_id: str, document_id: str, preview: dict[str, Any]) -> str:
        file_path = self._document_dir(kb_id, document_id) / "preview" / "preview_report.json"
        atomic_write_json(file_path, preview)
        return str(file_path)

    def save_published_chunks(self, kb_id: str, document_id: str, version: int, chunks: list[ChunkRecord]) -> str:
        file_path = self._document_dir(kb_id, document_id) / "published" / f"chunks_v{version}.jsonl"

        if file_path.exists():
            raise KnowledgeValidationError("Published version already exists and cannot be overwritten.")

        file_path.parent.mkdir(parents=True, exist_ok=True)

        with jsonlines.open(str(file_path), mode="w") as writer:
            for chunk in chunks:
                writer.write(chunk.model_dump())

        return str(file_path)

    def list_published_chunks(self, kb_id: str) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []

        for document in self.list_documents(kb_id):
            doc_dir = self._document_dir(kb_id, document.document_id) / "published"
            if not doc_dir.exists():
                continue

            for chunk_file in sorted(doc_dir.glob("chunks_v*.jsonl")):
                with jsonlines.open(str(chunk_file), mode="r") as reader:
                    for row in reader:
                        chunks.append(ChunkRecord.model_validate(row))

        return chunks

    def append_audit_event(self, kb_id: str, event: dict[str, Any]) -> str:
        return self.append(kb_id, event)

    def append(self, kb_id: str, event: dict[str, Any]) -> str:
        directory = self._audit_jobs_dir(kb_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "audit.jsonl"

        with jsonlines.open(str(path), mode="a") as writer:
            writer.write(event)

        return str(path)

    def list_audit_events(self, kb_id: str, limit: int = 100) -> list[dict[str, Any]]:
        path = self._audit_jobs_dir(kb_id) / "audit.jsonl"

        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []

        with jsonlines.open(str(path), mode="r") as reader:
            for row in reader:
                rows.append(row)

        return rows[-limit:]

    @contextmanager
    def acquire_write_lock(self, kb_id: str) -> Iterator[None]:
        self._ensure_kb_layout(kb_id)
        lock_file = self._kb_dir(kb_id) / ".write.lock"
        lock = FileLock(str(lock_file))
        with lock:
            yield

    def kb_health(self, kb_id: str) -> dict[str, Any]:
        kb = self.get_kb(kb_id)
        index_db = self._indexes_dir(kb_id) / "search.db"
        manifest = self._indexes_dir(kb_id) / "index_manifest.json"
        return {
            "kb_id": kb.kb_id,
            "enabled": kb.enabled,
            "index_exists": index_db.exists(),
            "manifest_exists": manifest.exists(),
            "document_count": len(self.list_documents(kb_id)),
            "collection_count": len(self.list_collections(kb_id)),
        }

    def index_db_path(self, kb_id: str) -> Path:
        self._ensure_kb_layout(kb_id)
        return self._indexes_dir(kb_id) / "search.db"

    def index_manifest_path(self, kb_id: str) -> Path:
        self._ensure_kb_layout(kb_id)
        return self._indexes_dir(kb_id) / "index_manifest.json"

    def write_index_manifest(self, kb_id: str, payload: dict[str, Any]) -> str:
        path = self.index_manifest_path(kb_id)
        atomic_write_json(path, payload)
        return str(path)

    def read_original_bytes(self, kb_id: str, document_id: str, version: int) -> bytes:
        original_dir = self._document_dir(kb_id, document_id) / "original"
        candidates = sorted(original_dir.glob(f"v{version}.*"))

        if not candidates:
            raise KnowledgeNotFoundError("Original document content not found.")

        return candidates[0].read_bytes()

    def published_exists(self, kb_id: str, document_id: str, version: int) -> bool:
        return (self._document_dir(kb_id, document_id) / "published" / f"chunks_v{version}.jsonl").exists()

    def original_extension(self, kb_id: str, document_id: str, version: int) -> str:
        original_dir = self._document_dir(kb_id, document_id) / "original"
        candidates = sorted(original_dir.glob(f"v{version}.*"))

        if not candidates:
            raise KnowledgeNotFoundError("Original document content not found.")

        return candidates[0].suffix
