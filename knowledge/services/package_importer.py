from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass, field
from contextlib import contextmanager
from io import BytesIO, TextIOWrapper
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Iterable
from zipfile import BadZipFile, ZipFile, ZipInfo

from knowledge.domain.errors import (
    KnowledgeError,
    KnowledgePackageError,
    KnowledgePackageSecurityError,
    KnowledgeValidationError,
)
from knowledge.domain.models import DocumentStatus, utc_now_iso
from knowledge.services.config import (
    package_allowed_archive_types,
    package_max_compressed_size_bytes,
    package_max_compression_ratio,
    package_max_directory_depth,
    package_max_file_count,
    package_max_uncompressed_size_bytes,
)
from knowledge.services.knowledge_services import KnowledgeServiceFacade
from knowledge.storage.utils import validate_identifier


_UNSUPPORTED_ID_CHARS = re.compile(r"[^a-z0-9_.-]+")
_REPEATED_DASHES = re.compile(r"-+")
_OS_ARTIFACTS = {".ds_store", "thumbs.db", "desktop.ini"}
_ROOT_METADATA_NAMES = {"collection_manifest.json"}
_ROOT_README_NAMES = {"readme", "readme.md", "readme.markdown", "readme.txt"}


@dataclass(frozen=True)
class PackageEntry:
    path: str
    size_bytes: int = 0
    is_directory: bool = False
    compressed_size: int | None = None


class PackageContentSource:
    @contextmanager
    def open(self, path: str):
        raise NotImplementedError


class ZipPackageSource(PackageContentSource):
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    @contextmanager
    def open(self, path: str):
        self.stream.seek(0)
        with ZipFile(self.stream, "r") as archive:
            with archive.open(path, "r") as member:
                yield member


class FolderPackageSource(PackageContentSource):
    def __init__(self, streams: dict[str, BinaryIO]):
        self.streams = streams

    @contextmanager
    def open(self, path: str):
        stream = self.streams[path]
        stream.seek(0)
        try:
            yield stream
        finally:
            stream.seek(0)


@dataclass
class PackageDocumentPlan:
    collection_id: str
    document_id: str
    original_filename: str
    relative_path: str
    extension: str
    size_bytes: int
    checksum: str
    supported: bool
    action: str
    skip_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_path: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "original_filename": self.original_filename,
            "relative_path": self.relative_path,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "supported": self.supported,
            "action": self.action,
            "skip_reason": self.skip_reason,
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
            "errors": list(self.errors),
        }


@dataclass
class PackageCollectionPlan:
    original_name: str
    collection_id: str
    normalized: bool
    exists: bool
    action: str
    documents: list[PackageDocumentPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_name": self.original_name,
            "collection_id": self.collection_id,
            "normalized": self.normalized,
            "exists": self.exists,
            "action": self.action,
            "warnings": list(self.warnings),
            "documents": [item.to_dict() for item in self.documents],
        }


@dataclass
class KnowledgePackagePlan:
    kb_id: str
    package_name: str
    package_root: str
    conflict_mode: str
    manifest_metadata: dict[str, Any]
    collections: list[PackageCollectionPlan]
    warnings: list[str]
    fatal_errors: list[dict[str, str]]
    source: PackageContentSource = field(repr=False)
    entries: list[PackageEntry] = field(default_factory=list, repr=False)

    @property
    def documents(self) -> list[PackageDocumentPlan]:
        return [document for collection in self.collections for document in collection.documents]

    @property
    def conflicts(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for collection in self.collections:
            if collection.exists:
                rows.append({"type": "existing_collection", "id": collection.collection_id})
            for document in collection.documents:
                rows.extend(
                    {"type": conflict, "id": document.document_id}
                    for conflict in document.conflicts
                )
        return rows

    @property
    def can_execute(self) -> bool:
        return not self.fatal_errors and not (
            self.conflict_mode == "fail" and self.conflicts
        )

    def to_dict(self) -> dict[str, Any]:
        documents = self.documents
        return {
            "package_name": self.package_name,
            "package_root": self.package_root,
            "manifest_metadata": self.manifest_metadata,
            "conflict_mode": self.conflict_mode,
            "can_execute": self.can_execute,
            "collection_count": len(self.collections),
            "document_count": len(documents),
            "supported_document_count": sum(item.supported for item in documents),
            "unsupported_document_count": sum(not item.supported for item in documents),
            "total_size_bytes": sum(item.size_bytes for item in documents),
            "collections": [item.to_dict() for item in self.collections],
            "conflicts": self.conflicts,
            "warnings": list(self.warnings),
            "fatal_errors": list(self.fatal_errors),
        }


def normalize_collection_id(folder_name: str) -> str:
    value = _normalize_identifier_text(folder_name)
    return validate_identifier(value, "collection_id")


def deterministic_document_id(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    without_extension = path.with_suffix("")
    value = _normalize_identifier_text("-".join(without_extension.parts))
    return validate_identifier(value, "document_id")


def _normalize_identifier_text(value: str) -> str:
    normalized = (value or "").strip().lower().replace(" ", "-")
    normalized = _UNSUPPORTED_ID_CHARS.sub("-", normalized)
    normalized = _REPEATED_DASHES.sub("-", normalized).strip("-._")
    normalized = normalized[:128].rstrip("-._")
    return normalized


class KnowledgePackageImporter:
    def __init__(self, service: KnowledgeServiceFacade):
        self.service = service

    def inspect_zip(
        self,
        *,
        kb_id: str,
        payload: bytes,
        filename: str,
        conflict_mode: str = "skip",
    ) -> KnowledgePackagePlan:
        return self.inspect_zip_stream(
            kb_id=kb_id,
            stream=BytesIO(payload),
            filename=filename,
            conflict_mode=conflict_mode,
            compressed_size=len(payload),
        )

    def inspect_zip_stream(
        self,
        *,
        kb_id: str,
        stream: BinaryIO,
        filename: str,
        conflict_mode: str = "skip",
        compressed_size: int | None = None,
    ) -> KnowledgePackagePlan:
        if "zip" not in package_allowed_archive_types():
            raise KnowledgePackageError("ZIP package import is disabled by configuration.")
        if not filename.lower().endswith(".zip"):
            raise KnowledgePackageError("Unsupported archive type. Only ZIP is allowed.")
        archive_size = compressed_size if compressed_size is not None else self._stream_size(stream)
        if archive_size > package_max_compressed_size_bytes():
            raise KnowledgePackageSecurityError("Package compressed size exceeds configured limit.")

        source = ZipPackageSource(stream)
        try:
            stream.seek(0)
            with ZipFile(stream, "r") as archive:
                entries = self._inspect_zip_members(archive)
        except BadZipFile as error:
            raise KnowledgePackageError("Malformed or unsupported ZIP archive.") from error

        package_name = PurePosixPath(filename).stem
        return self.build_import_plan(
            kb_id=kb_id,
            entries=entries,
            source=source,
            package_name=package_name,
            conflict_mode=conflict_mode,
        )

    def inspect_folder_upload(
        self,
        *,
        kb_id: str,
        files: Iterable[tuple[str, bytes]],
        package_name: str = "folder-upload",
        conflict_mode: str = "skip",
    ) -> KnowledgePackagePlan:
        streams = [(name, BytesIO(payload), len(payload)) for name, payload in files]
        return self.inspect_folder_streams(
            kb_id=kb_id,
            files=streams,
            package_name=package_name,
            conflict_mode=conflict_mode,
        )

    def inspect_folder_streams(
        self,
        *,
        kb_id: str,
        files: Iterable[tuple[str, BinaryIO, int | None]],
        package_name: str = "folder-upload",
        conflict_mode: str = "skip",
    ) -> KnowledgePackagePlan:
        stream_map: dict[str, BinaryIO] = {}
        entries: list[PackageEntry] = []
        for name, stream, size in files:
            if name in stream_map:
                raise KnowledgePackageError(f"Duplicate folder upload path: {name}")
            stream_map[name] = stream
            entries.append(
                PackageEntry(
                    path=name,
                    size_bytes=size if size is not None else self._stream_size(stream),
                )
            )
        first_parts = {
            self._validated_parts(entry.path)[0]
            for entry in entries
            if len(self._validated_parts(entry.path)) >= 2
        }
        if len(first_parts) == 1:
            root = next(iter(first_parts))
            entries.insert(0, PackageEntry(path=f"{root}/", is_directory=True))
        self._validate_entries(entries)
        return self.build_import_plan(
            kb_id=kb_id,
            entries=entries,
            source=FolderPackageSource(stream_map),
            package_name=package_name,
            conflict_mode=conflict_mode,
        )

    def _inspect_zip_members(self, archive: ZipFile) -> list[PackageEntry]:
        entries: list[PackageEntry] = []
        total_size = 0
        file_count = 0
        seen_paths: set[str] = set()

        for info in archive.infolist():
            self._validate_archive_member(info)
            if info.filename in seen_paths:
                raise KnowledgePackageError(f"Duplicate archive path: {info.filename}")
            seen_paths.add(info.filename)
            if info.is_dir():
                entries.append(PackageEntry(path=info.filename, is_directory=True))
                continue

            file_count += 1
            total_size += info.file_size
            if file_count > package_max_file_count():
                raise KnowledgePackageSecurityError("Package file count exceeds configured limit.")
            if total_size > package_max_uncompressed_size_bytes():
                raise KnowledgePackageSecurityError("Package uncompressed size exceeds configured limit.")
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > package_max_compression_ratio():
                raise KnowledgePackageSecurityError(
                    f"Package compression ratio exceeds configured limit: {info.filename}"
                )

            entries.append(
                PackageEntry(
                    path=info.filename,
                    size_bytes=info.file_size,
                    compressed_size=info.compress_size,
                )
            )

        return entries

    def _validate_archive_member(self, info: ZipInfo) -> None:
        self._validated_parts(info.filename)
        if info.flag_bits & 0x1:
            raise KnowledgePackageSecurityError(f"Encrypted archive members are not allowed: {info.filename}")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise KnowledgePackageSecurityError(f"Symbolic links are not allowed: {info.filename}")

    def _validate_entries(self, entries: list[PackageEntry]) -> None:
        files = [entry for entry in entries if not entry.is_directory]
        if len(files) > package_max_file_count():
            raise KnowledgePackageSecurityError("Package file count exceeds configured limit.")
        if sum(entry.size_bytes for entry in files) > package_max_uncompressed_size_bytes():
            raise KnowledgePackageSecurityError("Package uncompressed size exceeds configured limit.")
        for entry in entries:
            self._validated_parts(entry.path)

    @staticmethod
    def _stream_size(stream: BinaryIO) -> int:
        position = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(position)
        return size

    def _validated_parts(self, raw_path: str) -> tuple[str, ...]:
        if not raw_path or "\x00" in raw_path or "\\" in raw_path:
            raise KnowledgePackageSecurityError("Archive contains an invalid path.")
        if raw_path.startswith("/") or re.match(r"^[A-Za-z]:", raw_path):
            raise KnowledgePackageSecurityError(f"Absolute archive path is not allowed: {raw_path}")
        parts = tuple(part for part in PurePosixPath(raw_path).parts if part not in {""})
        if not parts or any(part in {".", ".."} for part in parts):
            raise KnowledgePackageSecurityError(f"Archive path traversal is not allowed: {raw_path}")
        if len(parts) > package_max_directory_depth() + 2:
            raise KnowledgePackageSecurityError(f"Package directory depth exceeds configured limit: {raw_path}")
        return parts

    def build_import_plan(
        self,
        *,
        kb_id: str,
        entries: list[PackageEntry],
        source: PackageContentSource,
        package_name: str,
        conflict_mode: str,
    ) -> KnowledgePackagePlan:
        validate_identifier(kb_id, "kb_id")
        if conflict_mode not in {"skip", "fail"}:
            raise KnowledgePackageError("Conflict mode must be 'skip' or 'fail'.")
        self._validate_entries(entries)

        usable_entries = [entry for entry in entries if not self._ignored_path(entry.path)]
        root = self._detect_package_root(usable_entries)
        manifest: dict[str, Any] = {}
        warnings: list[str] = []
        fatal_errors: list[dict[str, str]] = []
        collection_entries: dict[str, list[tuple[PackageEntry, tuple[str, ...]]]] = {}
        collection_directories: set[str] = set()

        for entry in usable_entries:
            parts = self._validated_parts(entry.path)
            relative_parts = parts[1:] if root and parts[0] == root else parts
            if not relative_parts:
                continue
            if len(relative_parts) == 1:
                name = relative_parts[0]
                lowered = name.lower()
                if entry.is_directory:
                    collection_directories.add(name)
                elif lowered in _ROOT_METADATA_NAMES:
                    try:
                        with source.open(entry.path) as manifest_stream:
                            reader = TextIOWrapper(manifest_stream, encoding="utf-8-sig")
                            try:
                                parsed = json.load(reader)
                            finally:
                                reader.detach()
                        if not isinstance(parsed, dict):
                            raise ValueError("manifest must be a JSON object")
                        manifest = parsed
                    except Exception as error:
                        fatal_errors.append({"code": "invalid_manifest", "path": entry.path, "message": str(error)})
                elif lowered in _ROOT_README_NAMES:
                    warnings.append(f"Root README ignored: {entry.path}")
                else:
                    warnings.append(f"Root-level file ignored: {entry.path}")
                continue

            collection_name = relative_parts[0]
            collection_directories.add(collection_name)
            if entry.is_directory:
                continue
            collection_entries.setdefault(collection_name, []).append((entry, relative_parts[1:]))

        existing_collections = {item.collection_id for item in self.service.list_collections(kb_id)}
        existing_documents = {item.document_id: item for item in self.service.list_documents(kb_id)}
        existing_checksums = {
            item.checksum: item.document_id
            for item in existing_documents.values()
            if item.status != DocumentStatus.ARCHIVED
        }
        normalized_collections: dict[str, str] = {}
        collections: list[PackageCollectionPlan] = []
        used_document_ids: set[str] = set()
        planned_checksums: set[str] = set()

        for original_name in sorted(collection_directories | set(collection_entries)):
            try:
                collection_id = normalize_collection_id(original_name)
            except KnowledgeValidationError as error:
                fatal_errors.append({"code": "invalid_collection_id", "path": original_name, "message": str(error)})
                continue
            if collection_id in normalized_collections and normalized_collections[collection_id] != original_name:
                fatal_errors.append({
                    "code": "duplicate_collection_id",
                    "path": original_name,
                    "message": f"Collection folders normalize to the same ID: {normalized_collections[collection_id]!r} and {original_name!r}.",
                })
                continue
            normalized_collections[collection_id] = original_name
            exists = collection_id in existing_collections
            collection = PackageCollectionPlan(
                original_name=original_name,
                collection_id=collection_id,
                normalized=collection_id != original_name,
                exists=exists,
                action="reuse" if exists and conflict_mode == "skip" else ("conflict" if exists else "create"),
            )
            if collection.normalized:
                collection.warnings.append(f"Collection name normalized from {original_name!r} to {collection_id!r}.")

            files = collection_entries.get(original_name, [])
            if not files:
                collection.warnings.append("Collection directory is empty.")
                warnings.append(f"Empty collection: {original_name}")

            for entry, relative_parts in sorted(files, key=lambda item: item[0].path):
                relative_path = "/".join(relative_parts)
                extension = PurePosixPath(relative_path).suffix.lower()
                errors: list[str] = []
                supported = True
                skip_reason = ""
                try:
                    self.service.package_parsers.validate_extension(extension)
                    with source.open(entry.path) as content_stream:
                        self.service.package_parsers.inspect(content_stream, extension)
                except KnowledgeValidationError as error:
                    if str(error).startswith("Unsupported format:"):
                        supported = False
                        skip_reason = str(error)
                    else:
                        errors.append(str(error))

                try:
                    document_id = deterministic_document_id(relative_path)
                except KnowledgeValidationError as error:
                    fatal_errors.append({"code": "invalid_document_id", "path": entry.path, "message": str(error)})
                    continue

                if document_id in used_document_ids:
                    suffix = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:8]
                    base = document_id[: 128 - len(suffix) - 1].rstrip("-._")
                    document_id = validate_identifier(f"{base}-{suffix}", "document_id")
                    warnings.append(f"Document ID collision resolved with stable checksum: {entry.path}")
                if document_id in used_document_ids:
                    fatal_errors.append({"code": "duplicate_document_id", "path": entry.path, "message": f"Duplicate document ID: {document_id}"})
                    continue
                used_document_ids.add(document_id)

                checksum = self._content_checksum(source, entry.path)
                conflicts: list[str] = []
                if document_id in existing_documents:
                    conflicts.append("existing_document")
                elif checksum in existing_checksums:
                    conflicts.append("existing_content_checksum")
                elif checksum in planned_checksums:
                    conflicts.append("duplicate_package_content_checksum")
                planned_checksums.add(checksum)
                if errors:
                    fatal_errors.append({"code": "invalid_document", "path": entry.path, "message": errors[0]})

                action = "import"
                if not supported:
                    action = "skip"
                elif conflicts:
                    action = "skip" if conflict_mode == "skip" else "conflict"
                collection.documents.append(
                    PackageDocumentPlan(
                        collection_id=collection_id,
                        document_id=document_id,
                        original_filename=PurePosixPath(relative_path).name,
                        relative_path=relative_path,
                        extension=extension,
                        size_bytes=entry.size_bytes,
                        checksum=checksum,
                        supported=supported,
                        action=action,
                        skip_reason=skip_reason,
                        conflicts=conflicts,
                        errors=errors,
                        source_path=entry.path,
                    )
                )
            collections.append(collection)

        if not collections and not fatal_errors:
            fatal_errors.append({"code": "no_collections", "path": root, "message": "No collection directories were detected."})

        return KnowledgePackagePlan(
            kb_id=kb_id,
            package_name=root or _normalize_identifier_text(package_name) or "package",
            package_root=root,
            conflict_mode=conflict_mode,
            manifest_metadata=manifest,
            collections=collections,
            warnings=warnings,
            fatal_errors=fatal_errors,
            source=source,
            entries=list(entries),
        )

    @staticmethod
    def _content_checksum(source: PackageContentSource, path: str) -> str:
        digest = hashlib.sha256()
        with source.open(path) as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def execute_import(
        self,
        plan: KnowledgePackagePlan,
        *,
        auto_publish: bool = False,
        actor: str = "maintainer",
    ) -> dict[str, Any]:
        with self.service.storage.acquire_write_lock(plan.kb_id):
            return self._execute_import(
                plan,
                auto_publish=auto_publish,
                actor=actor,
            )

    def _execute_import(
        self,
        plan: KnowledgePackagePlan,
        *,
        auto_publish: bool = False,
        actor: str = "maintainer",
    ) -> dict[str, Any]:
        current = self.build_import_plan(
            kb_id=plan.kb_id,
            entries=plan.entries,
            source=plan.source,
            package_name=plan.package_name,
            conflict_mode=plan.conflict_mode,
        )
        if not current.can_execute:
            return {"status": "blocked", "plan": current.to_dict(), "collections": [], "documents": []}

        collection_results: list[dict[str, Any]] = []
        document_results: list[dict[str, Any]] = []
        for collection in current.collections:
            if collection.action == "create":
                try:
                    self.service.create_collection(
                        current.kb_id,
                        collection.collection_id,
                        collection.original_name,
                        f"Imported from package {current.package_name}",
                        100,
                        actor,
                    )
                    collection_results.append({"collection_id": collection.collection_id, "status": "created"})
                except KnowledgeError as error:
                    collection_results.append({"collection_id": collection.collection_id, "status": "failed", "error": str(error)})
                    for document in collection.documents:
                        document_results.append({"document_id": document.document_id, "status": "failed", "error": "Collection creation failed."})
                    continue
            else:
                collection_results.append({"collection_id": collection.collection_id, "status": collection.action})

            for document in collection.documents:
                if document.action != "import":
                    document_results.append({
                        "document_id": document.document_id,
                        "collection_id": collection.collection_id,
                        "status": document.action,
                        "reason": document.skip_reason or ", ".join(document.conflicts),
                    })
                    continue
                try:
                    with current.source.open(document.source_path) as content_stream:
                        uploaded = self.service.ingest_package_document(
                            kb_id=current.kb_id,
                            collection_id=collection.collection_id,
                            document_id=document.document_id,
                            title=document.original_filename,
                            source_type="knowledge-package",
                            external_id=f"package:{current.package_name}:{collection.original_name}/{document.relative_path}",
                            confidence=1.0,
                            effective_from=None,
                            effective_to=None,
                            content_stream=content_stream,
                            content_checksum_value=document.checksum,
                            extension=document.extension,
                            actor=actor,
                        )
                    result = {
                        "document_id": document.document_id,
                        "collection_id": collection.collection_id,
                        "status": "uploaded",
                        "source_path": f"{collection.original_name}/{document.relative_path}",
                    }
                    if auto_publish:
                        publish_result = self.service.publish_document(current.kb_id, uploaded.document_id, actor)
                        result["status"] = publish_result.get("status", "published")
                    document_results.append(result)
                except Exception as error:
                    document_results.append({
                        "document_id": document.document_id,
                        "collection_id": collection.collection_id,
                        "status": "failed",
                        "error": str(error) if isinstance(error, KnowledgeError) else "Unexpected storage or import error.",
                    })

        summary = {
            "status": "completed_with_errors" if any(item["status"] == "failed" for item in document_results + collection_results) else "completed",
            "package_name": current.package_name,
            "auto_publish": auto_publish,
            "collections": collection_results,
            "documents": document_results,
        }
        self.service.storage.append_audit_event(
            current.kb_id,
            {
                "ts": utc_now_iso(),
                "event": "knowledge_package_imported",
                "actor": actor,
                "package_name": current.package_name,
                "conflict_mode": current.conflict_mode,
                "auto_publish": auto_publish,
                "collection_count": len(collection_results),
                "document_count": len(document_results),
                "status": summary["status"],
            },
        )
        return summary

    def _detect_package_root(self, entries: list[PackageEntry]) -> str:
        paths = [self._validated_parts(entry.path) for entry in entries]
        if not paths:
            return ""
        first_parts = {parts[0] for parts in paths}
        if len(first_parts) != 1:
            return ""
        candidate = next(iter(first_parts))
        has_explicit_root = any(entry.is_directory and entry.path.rstrip("/") == candidate for entry in entries)
        has_root_metadata = any(
            len(parts) == 2 and parts[0] == candidate and parts[1].lower() in (_ROOT_METADATA_NAMES | _ROOT_README_NAMES)
            for parts in paths
        )
        second_parts = {parts[1] for parts in paths if len(parts) >= 2}
        return candidate if has_explicit_root or has_root_metadata or len(second_parts) >= 2 else ""

    def _ignored_path(self, raw_path: str) -> bool:
        parts = self._validated_parts(raw_path)
        lowered = [part.lower() for part in parts]
        return any(
            part.startswith(".") or part == "__macosx" or part in _OS_ARTIFACTS
            for part in lowered
        )
