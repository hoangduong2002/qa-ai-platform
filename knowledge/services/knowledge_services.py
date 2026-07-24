from __future__ import annotations

from collections.abc import Iterable
import json
import logging
from pathlib import Path
from typing import Any

from app.config.env_loader import PROJECT_ROOT
from knowledge.domain.errors import (
    KnowledgeConflictError,
    KnowledgeDeletionError,
    KnowledgeValidationError,
)
from knowledge.domain.models import (
    ChunkRecord,
    CollectionMetadata,
    DocumentMetadata,
    DocumentStatus,
    KnowledgeBaseDeletionImpact,
    KnowledgeBaseDeletionResult,
    KnowledgeBaseMetadata,
    SearchRequest,
    utc_now_iso,
)
from knowledge.ingestion.parser_registry import ParserRegistry
from knowledge.ingestion.streaming_package_parsers import StreamingPackageParserRegistry
from knowledge.search.sqlite_fts_retriever import SQLiteFTSKnowledgeRetriever
from knowledge.services.config import default_top_k, max_upload_size_bytes
from knowledge.services.jira_project_keys import (
    normalize_jira_project_key,
    normalize_jira_project_keys,
)
from knowledge.storage.filesystem_storage import FileSystemKnowledgeStorage
from knowledge.storage.utils import content_checksum, validate_identifier

logger = logging.getLogger(__name__)


class KnowledgeServiceFacade:
    def __init__(self, root: Path, requirements_root: Path | None = None):
        self.storage = FileSystemKnowledgeStorage(root)
        self.requirements_root = (
            requirements_root.resolve()
            if requirements_root is not None
            else (PROJECT_ROOT / "requirements").resolve()
        )
        self.parsers = ParserRegistry()
        self.package_parsers = StreamingPackageParserRegistry()
        self.retriever = SQLiteFTSKnowledgeRetriever(self.storage.index_db_path)

    def create_kb(
        self,
        kb_id: str,
        name: str,
        description: str,
        actor: str,
        jira_project_keys: Iterable[str] | None = None,
    ) -> KnowledgeBaseMetadata:
        normalized_keys = self.normalize_jira_project_keys(jira_project_keys)
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise KnowledgeValidationError("Knowledge Base name is required.")
        now = utc_now_iso()
        kb = KnowledgeBaseMetadata(
            kb_id=validate_identifier(kb_id, "kb_id"),
            name=normalized_name,
            description=(description or "").strip(),
            jira_project_keys=normalized_keys,
            enabled=True,
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
        )
        with self.storage.acquire_kb_metadata_lock():
            self.ensure_jira_project_keys_available(normalized_keys)
            created = self.storage.create_kb(kb)
            self.storage.append_audit_event(
                kb_id,
                {
                    "ts": now,
                    "event": "kb_created",
                    "actor": actor,
                    "kb_id": kb_id,
                },
            )
        return created

    def list_kbs(self):
        return self.storage.list_kbs()

    def get_kb(self, kb_id: str):
        return self.storage.get_kb(kb_id)

    def _historical_snapshot_count(self, kb_id: str) -> int:
        if not self.requirements_root.exists():
            return 0
        count = 0
        for path in self.requirements_root.glob("*/knowledge/snapshots/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("knowledge_base_id") == kb_id:
                count += 1
        return count

    def deletion_impact(self, kb_id: str) -> KnowledgeBaseDeletionImpact:
        kb = self.storage.get_kb(kb_id)
        active = self.storage.operation_is_active(kb_id)
        return KnowledgeBaseDeletionImpact(
            kb_id=kb.kb_id,
            name=kb.name,
            collection_count=len(self.storage.list_collections(kb_id)),
            document_count=len(self.storage.list_documents(kb_id)),
            jira_project_keys=list(kb.jira_project_keys),
            historical_snapshot_count=self._historical_snapshot_count(kb_id),
            active_operations=1 if active else 0,
            can_delete=not active,
            blocking_reasons=(
                ["An active Knowledge Base operation must finish before deletion."]
                if active
                else []
            ),
        )

    def delete_kb(
        self,
        kb_id: str,
        *,
        confirmation: str,
        actor: str,
    ) -> KnowledgeBaseDeletionResult:
        kb_id = validate_identifier(kb_id, "kb_id")
        if confirmation != kb_id:
            raise KnowledgeValidationError(
                "Deletion confirmation must exactly match the Knowledge Base ID."
            )

        with self.storage.acquire_kb_metadata_lock():
            with self.storage.acquire_write_lock(kb_id, timeout=0):
                impact = self.deletion_impact(kb_id)
                self.storage.archive_audit_events_for_deletion(kb_id)
                started_at = utc_now_iso()
                self.storage.append_deletion_audit_event(
                    kb_id,
                    {
                        "ts": started_at,
                        "event": "kb_deletion_started",
                        "actor": actor,
                        "kb_id": kb_id,
                        "impact": impact.model_dump(),
                    },
                )
                try:
                    self.storage.delete_kb_directory(kb_id)
                except Exception as error:
                    self.storage.append_deletion_audit_event(
                        kb_id,
                        {
                            "ts": utc_now_iso(),
                            "event": "kb_deletion_failed",
                            "actor": actor,
                            "kb_id": kb_id,
                            "error_type": type(error).__name__,
                        },
                    )
                    logger.exception("Knowledge Base deletion failed for kb_id=%s", kb_id)
                    if isinstance(error, KnowledgeDeletionError):
                        raise
                    raise

                deleted_at = utc_now_iso()
                result = KnowledgeBaseDeletionResult(
                    kb_id=kb_id,
                    name=impact.name,
                    deleted_collection_count=impact.collection_count,
                    deleted_document_count=impact.document_count,
                    released_jira_project_keys=impact.jira_project_keys,
                    historical_snapshot_count=impact.historical_snapshot_count,
                    deleted_at=deleted_at,
                    deleted_by=actor,
                )
                self.storage.append_deletion_audit_event(
                    kb_id,
                    {
                        "ts": deleted_at,
                        "event": "kb_deleted",
                        "actor": actor,
                        **result.model_dump(),
                    },
                )
                return result

    def update_kb(self, kb_id: str, patch: dict[str, Any], actor: str):
        safe_patch = dict(patch)
        if "jira_project_keys" in safe_patch:
            safe_patch["jira_project_keys"] = self.normalize_jira_project_keys(
                safe_patch["jira_project_keys"]
            )
        if "name" in safe_patch:
            safe_patch["name"] = str(safe_patch["name"] or "").strip()
            if not safe_patch["name"]:
                raise KnowledgeValidationError("Knowledge Base name is required.")
        if "description" in safe_patch:
            safe_patch["description"] = str(safe_patch["description"] or "").strip()
        safe_patch["updated_by"] = actor
        safe_patch["updated_at"] = utc_now_iso()
        with self.storage.acquire_kb_metadata_lock():
            self.storage.get_kb(kb_id)
            if "jira_project_keys" in safe_patch:
                self.ensure_jira_project_keys_available(
                    safe_patch["jira_project_keys"],
                    current_kb_id=kb_id,
                )
            updated = self.storage.update_kb(kb_id, safe_patch)
            self.storage.append_audit_event(
                kb_id,
                {
                    "ts": utc_now_iso(),
                    "event": "kb_updated",
                    "actor": actor,
                    "patch": safe_patch,
                },
            )
        return updated

    @staticmethod
    def normalize_jira_project_keys(values: Iterable[str] | None) -> list[str]:
        """Normalize, validate, and deduplicate Jira project keys."""
        return normalize_jira_project_keys(values)

    def find_kb_by_jira_project_key(self, project_key: str) -> KnowledgeBaseMetadata | None:
        """Find the Knowledge Base assigned to a normalized Jira project key."""
        normalized = normalize_jira_project_key(project_key)
        for kb in self.storage.list_kbs():
            if normalized in self.normalize_jira_project_keys(kb.jira_project_keys):
                return kb
        return None

    def ensure_jira_project_keys_available(
        self,
        project_keys: Iterable[str],
        current_kb_id: str | None = None,
    ) -> None:
        """Reject Jira keys already assigned to another Knowledge Base."""
        normalized_keys = self.normalize_jira_project_keys(project_keys)
        requested = set(normalized_keys)
        for kb in self.storage.list_kbs():
            if current_kb_id is not None and kb.kb_id == current_kb_id:
                continue
            for project_key in self.normalize_jira_project_keys(kb.jira_project_keys):
                if project_key in requested:
                    raise KnowledgeConflictError(
                        f'Jira project key "{project_key}" is already assigned '
                        f'to Knowledge Base "{kb.kb_id}".'
                    )

    def resolve_kb_by_jira_project_key(self, project_key: str) -> KnowledgeBaseMetadata | None:
        """Resolve a Jira project key without changing Jira requirement workflows."""
        return self.find_kb_by_jira_project_key(project_key)

    def kb_health(self, kb_id: str) -> dict[str, Any]:
        storage_health = self.storage.kb_health(kb_id)
        storage_health["fts5_supported"] = self.retriever.verify_fts5()
        return storage_health

    def create_collection(self, kb_id: str, collection_id: str, name: str, description: str, priority: int, actor: str):
        now = utc_now_iso()
        collection = CollectionMetadata(
            kb_id=kb_id,
            collection_id=validate_identifier(collection_id, "collection_id"),
            name=name.strip(),
            description=description.strip(),
            priority=priority,
            archived=False,
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
        )
        with self.storage.acquire_write_lock(kb_id):
            created = self.storage.create_collection(collection)
            self.storage.append_audit_event(kb_id, {"ts": now, "event": "collection_created", "actor": actor, "collection_id": collection_id})
            return created

    def list_collections(self, kb_id: str):
        self.storage.get_kb(kb_id)
        return self.storage.list_collections(kb_id)

    def update_collection(self, kb_id: str, collection_id: str, patch: dict[str, Any], actor: str):
        patch["updated_by"] = actor
        patch["updated_at"] = utc_now_iso()
        with self.storage.acquire_write_lock(kb_id):
            updated = self.storage.update_collection(kb_id, collection_id, patch)
            self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "collection_updated", "actor": actor, "collection_id": collection_id})
            return updated

    def _validate_no_duplicate(self, kb_id: str, external_id: str | None, checksum: str):
        for item in self.storage.list_documents(kb_id):
            if external_id and item.external_id == external_id and item.status != DocumentStatus.ARCHIVED:
                raise KnowledgeValidationError("Duplicate external_id in knowledge base.")

            if item.checksum == checksum and item.status != DocumentStatus.ARCHIVED:
                raise KnowledgeValidationError("Duplicate content checksum in knowledge base.")

    def upload_document(self, **kwargs: Any) -> DocumentMetadata:
        kb_id = str(kwargs.get("kb_id") or "")
        with self.storage.acquire_write_lock(kb_id):
            return self._upload_document(**kwargs)

    def _upload_document(
        self,
        *,
        kb_id: str,
        collection_id: str,
        document_id: str,
        title: str,
        source_type: str,
        external_id: str | None,
        confidence: float,
        effective_from: str | None,
        effective_to: str | None,
        raw_content: bytes,
        extension: str,
        actor: str,
    ) -> DocumentMetadata:
        if len(raw_content) > max_upload_size_bytes():
            raise KnowledgeValidationError("File size exceeds configured limit.")

        checksum = content_checksum(raw_content)
        self._validate_no_duplicate(kb_id, external_id, checksum)

        now = utc_now_iso()
        document = DocumentMetadata(
            kb_id=kb_id,
            collection_id=collection_id,
            document_id=validate_identifier(document_id, "document_id"),
            title=title.strip(),
            status=DocumentStatus.UPLOADED,
            version=1,
            checksum=checksum,
            effective_from=effective_from,
            effective_to=effective_to,
            confidence=confidence,
            source_type=source_type,
            external_id=external_id,
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )

        doc = self.storage.save_document(document, raw_content, extension)
        preview = self._preview_document(kb_id, document.document_id, actor=actor)
        doc = self.storage.update_document(kb_id, document.document_id, {
            "status": DocumentStatus.READY_FOR_REVIEW,
            "parsing_preview": preview,
            "updated_at": utc_now_iso(),
            "updated_by": actor,
        })
        self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "document_uploaded", "actor": actor, "document_id": document.document_id})
        return doc

    def ingest_package_document(self, **kwargs: Any) -> DocumentMetadata:
        kb_id = str(kwargs.get("kb_id") or "")
        with self.storage.acquire_write_lock(kb_id):
            return self._ingest_package_document(**kwargs)

    def _ingest_package_document(
        self,
        *,
        kb_id: str,
        collection_id: str,
        document_id: str,
        title: str,
        source_type: str,
        external_id: str | None,
        confidence: float,
        effective_from: str | None,
        effective_to: str | None,
        content_stream,
        content_checksum_value: str,
        extension: str,
        actor: str,
    ) -> DocumentMetadata:
        """Package-only streaming ingestion; manual upload limits do not apply."""
        self.package_parsers.validate_extension(extension)
        self._validate_no_duplicate(kb_id, external_id, content_checksum_value)
        now = utc_now_iso()
        document = DocumentMetadata(
            kb_id=kb_id,
            collection_id=collection_id,
            document_id=validate_identifier(document_id, "document_id"),
            title=title.strip(),
            status=DocumentStatus.UPLOADED,
            version=1,
            checksum=content_checksum_value,
            effective_from=effective_from,
            effective_to=effective_to,
            confidence=confidence,
            source_type=source_type,
            external_id=external_id,
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        doc = self.storage.save_document_stream(
            document,
            content_stream,
            extension,
            content_checksum_value,
        )
        with self.storage.open_original_stream(kb_id, document.document_id, document.version) as stream:
            preview = self.package_parsers.inspect(stream, extension)
        doc = self.storage.update_document(
            kb_id,
            document.document_id,
            {
                "status": DocumentStatus.READY_FOR_REVIEW,
                "parsing_preview": preview,
                "updated_at": utc_now_iso(),
                "updated_by": actor,
            },
        )
        self.storage.save_preview(kb_id, document.document_id, preview)
        self.storage.append_audit_event(
            kb_id,
            {
                "ts": utc_now_iso(),
                "event": "package_document_ingested",
                "actor": actor,
                "document_id": document.document_id,
            },
        )
        return doc

    def preview_document(self, kb_id: str, document_id: str, actor: str) -> dict[str, Any]:
        with self.storage.acquire_write_lock(kb_id):
            return self._preview_document(kb_id, document_id, actor)

    def _preview_document(self, kb_id: str, document_id: str, actor: str) -> dict[str, Any]:
        document = self.storage.get_document(kb_id, document_id)
        self.storage.update_document(kb_id, document_id, {"status": DocumentStatus.VALIDATING, "updated_at": utc_now_iso(), "updated_by": actor})

        raw_bytes = self.storage.read_original_bytes(kb_id, document_id, document.version)
        decoded = self.parsers.decode_bytes(raw_bytes)

        self.storage.update_document(kb_id, document_id, {"status": DocumentStatus.PARSING, "updated_at": utc_now_iso(), "updated_by": actor})
        extension = self.storage.original_extension(kb_id, document_id, document.version)
        parser = self.parsers.parser_for(extension)

        chunks = parser.parse(decoded)
        preview = {
            "valid": True,
            "chunk_count": len(chunks),
            "sample_chunks": chunks[:3],
            "warnings": [],
        }

        self.storage.save_preview(kb_id, document_id, preview)
        return preview

    def get_document(self, kb_id: str, document_id: str):
        return self.storage.get_document(kb_id, document_id)

    def list_documents(self, kb_id: str, collection_id: str | None = None):
        self.storage.get_kb(kb_id)
        return self.storage.list_documents(kb_id, collection_id)

    def _build_chunks(self, document: DocumentMetadata):
        extension = self.storage.original_extension(document.kb_id, document.document_id, document.version)
        if (document.parsing_preview or {}).get("streaming") is True:
            with self.storage.open_original_stream(
                document.kb_id, document.document_id, document.version
            ) as stream:
                parts = self.package_parsers.iter_chunks(stream, extension)
                yield from self._chunk_records(document, parts)
            return
        raw_bytes = self.storage.read_original_bytes(document.kb_id, document.document_id, document.version)
        decoded = self.parsers.decode_bytes(raw_bytes)
        parser = self.parsers.parser_for(extension)
        yield from self._chunk_records(document, parser.parse(decoded))

    def _chunk_records(self, document: DocumentMetadata, parts):
        for index, part in enumerate(parts, start=1):
            yield ChunkRecord(
                kb_id=document.kb_id,
                collection_id=document.collection_id,
                document_id=document.document_id,
                version=document.version,
                chunk_index=index,
                content=part,
                confidence=document.confidence,
                effective_from=document.effective_from,
                effective_to=document.effective_to,
                checksum=document.checksum,
                source_citation=f"{document.document_id}:v{document.version}:chunk{index}",
                is_active=document.status != DocumentStatus.SUPERSEDED,
            )

    def publish_document(self, kb_id: str, document_id: str, actor: str) -> dict[str, Any]:
        with self.storage.acquire_write_lock(kb_id):
            document = self.storage.get_document(kb_id, document_id)

            if document.status == DocumentStatus.INDEXED and self.storage.published_exists(kb_id, document_id, document.version):
                return {"status": "idempotent", "document_id": document_id, "version": document.version}

            preview = document.parsing_preview or {}
            if not preview.get("valid", False):
                raise KnowledgeValidationError("Document preview is invalid. Publish is blocked.")

            previous_status = document.status

            try:
                self.storage.update_document(kb_id, document_id, {"status": DocumentStatus.PUBLISHING, "updated_at": utc_now_iso(), "updated_by": actor})
                chunks = self._build_chunks(document)
                chunks_file = self.storage.save_published_chunks(kb_id, document_id, document.version, chunks)

                all_chunks = self.storage.list_published_chunks(kb_id)
                index_info = self.retriever.rebuild_index(kb_id, all_chunks)

                manifest = {
                    "kb_id": kb_id,
                    "updated_at": utc_now_iso(),
                    "document_count": len(self.storage.list_documents(kb_id)),
                    "chunk_count": len(all_chunks),
                    "indexed_document_id": document_id,
                    "indexed_version": document.version,
                }
                self.storage.write_index_manifest(kb_id, manifest)

                history = list(document.publish_history)
                history.append(
                    {
                        "published_at": utc_now_iso(),
                        "version": document.version,
                        "checksum": document.checksum,
                        "chunks_file": chunks_file,
                        "index": index_info,
                    }
                )

                updated = self.storage.update_document(
                    kb_id,
                    document_id,
                    {
                        "status": DocumentStatus.INDEXED,
                        "publish_history": history,
                        "last_error": "",
                        "updated_at": utc_now_iso(),
                        "updated_by": actor,
                    },
                )

                self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "document_published", "actor": actor, "document_id": document_id, "version": document.version})
                return {"status": "published", "document": updated.model_dump()}

            except Exception as error:
                self.storage.update_document(
                    kb_id,
                    document_id,
                    {
                        "status": DocumentStatus.FAILED,
                        "last_error": str(error),
                        "updated_at": utc_now_iso(),
                        "updated_by": actor,
                    },
                )
                self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "publish_failed", "actor": actor, "document_id": document_id, "error": str(error)})
                raise

    def retry_publish(self, kb_id: str, document_id: str, actor: str) -> dict[str, Any]:
        return self.publish_document(kb_id, document_id, actor)

    def archive_document(self, kb_id: str, document_id: str, actor: str) -> DocumentMetadata:
        with self.storage.acquire_write_lock(kb_id):
            return self._archive_document(kb_id, document_id, actor)

    def _archive_document(self, kb_id: str, document_id: str, actor: str) -> DocumentMetadata:
        doc = self.storage.update_document(
            kb_id,
            document_id,
            {
                "status": DocumentStatus.ARCHIVED,
                "updated_at": utc_now_iso(),
                "updated_by": actor,
            },
        )
        self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "document_archived", "actor": actor, "document_id": document_id})
        return doc

    def supersede_document(self, kb_id: str, document_id: str, replacement_document_id: str, actor: str) -> dict[str, Any]:
        with self.storage.acquire_write_lock(kb_id):
            return self._supersede_document(
                kb_id, document_id, replacement_document_id, actor
            )

    def _supersede_document(self, kb_id: str, document_id: str, replacement_document_id: str, actor: str) -> dict[str, Any]:
        original = self.storage.get_document(kb_id, document_id)
        replacement = self.storage.get_document(kb_id, replacement_document_id)

        self.storage.update_document(
            kb_id,
            document_id,
            {
                "status": DocumentStatus.SUPERSEDED,
                "superseded_by_document_id": replacement_document_id,
                "updated_at": utc_now_iso(),
                "updated_by": actor,
            },
        )

        self.storage.update_document(
            kb_id,
            replacement_document_id,
            {
                "supersedes_document_id": document_id,
                "updated_at": utc_now_iso(),
                "updated_by": actor,
            },
        )

        self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "document_superseded", "actor": actor, "document_id": document_id, "replacement_document_id": replacement_document_id})

        all_chunks = self.storage.list_published_chunks(kb_id)
        for chunk in all_chunks:
            if chunk.document_id == document_id:
                chunk.is_active = False
            if chunk.document_id == replacement.document_id:
                chunk.is_active = True
        self.retriever.rebuild_index(kb_id, all_chunks)

        return {
            "superseded": original.document_id,
            "replacement": replacement.document_id,
        }

    def search(self, kb_id: str, request: SearchRequest):
        self.storage.get_kb(kb_id)
        if request.top_k <= 0:
            request.top_k = default_top_k()
        return self.retriever.search(kb_id, request)

    def reindex(self, kb_id: str, actor: str) -> dict[str, Any]:
        with self.storage.acquire_write_lock(kb_id):
            chunks = self.storage.list_published_chunks(kb_id)
            result = self.retriever.rebuild_index(kb_id, chunks)
            self.storage.write_index_manifest(
                kb_id,
                {
                    "kb_id": kb_id,
                    "updated_at": utc_now_iso(),
                    "chunk_count": len(chunks),
                    "actor": actor,
                },
            )
            self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "index_rebuilt", "actor": actor, "chunk_count": len(chunks)})
            return result

    def validate_kb(self, kb_id: str) -> dict[str, Any]:
        kb = self.storage.get_kb(kb_id)
        collections = self.storage.list_collections(kb_id)
        documents = self.storage.list_documents(kb_id)
        errors: list[str] = []

        if not collections:
            errors.append("No collections found.")

        if not documents:
            errors.append("No documents found.")

        return {
            "kb_id": kb_id,
            "valid": len(errors) == 0,
            "errors": errors,
            "kb": kb.model_dump(),
            "collection_count": len(collections),
            "document_count": len(documents),
        }

    def verify_metadata(self, kb_id: str) -> dict[str, Any]:
        docs = self.storage.list_documents(kb_id)
        issues: list[str] = []
        seen_external: set[str] = set()

        for doc in docs:
            if doc.external_id:
                if doc.external_id in seen_external:
                    issues.append(f"Duplicate external_id: {doc.external_id}")
                seen_external.add(doc.external_id)

            if not doc.checksum:
                issues.append(f"Missing checksum: {doc.document_id}")

        return {
            "kb_id": kb_id,
            "ok": len(issues) == 0,
            "issues": issues,
        }

    def recover(self, kb_id: str, actor: str) -> dict[str, Any]:
        with self.storage.acquire_write_lock(kb_id):
            return self._recover(kb_id, actor)

    def _recover(self, kb_id: str, actor: str) -> dict[str, Any]:
        docs = self.storage.list_documents(kb_id)
        recovered: list[str] = []

        for doc in docs:
            if doc.status == DocumentStatus.PUBLISHING:
                self.storage.update_document(kb_id, doc.document_id, {
                    "status": DocumentStatus.FAILED,
                    "last_error": "Recovered from interrupted publishing state.",
                    "updated_at": utc_now_iso(),
                    "updated_by": actor,
                })
                recovered.append(doc.document_id)

        self.storage.append_audit_event(kb_id, {"ts": utc_now_iso(), "event": "recovery", "actor": actor, "recovered_documents": recovered})

        return {
            "kb_id": kb_id,
            "recovered_documents": recovered,
        }

    def audit(self, kb_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.storage.get_kb(kb_id)
        return self.storage.list_audit_events(kb_id, limit=limit)
