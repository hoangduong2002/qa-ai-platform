from __future__ import annotations

import json
import stat
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from knowledge.domain.errors import (
    KnowledgePackageError,
    KnowledgePackageSecurityError,
    KnowledgeValidationError,
)
from knowledge.domain.models import DocumentStatus
from knowledge.services.knowledge_services import KnowledgeServiceFacade
from knowledge.services.package_importer import KnowledgePackageImporter


def _service(tmp_path: Path) -> KnowledgeServiceFacade:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "Knowledge", "", "tester")
    return service


def _zip(
    files: dict[str, bytes | str],
    *,
    directories: tuple[str, ...] = ("weclever_rag_knowledge/",),
    compression: int = ZIP_STORED,
) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for directory in directories:
            archive.writestr(directory, b"")
        for path, value in files.items():
            archive.writestr(path, value.encode("utf-8") if isinstance(value, str) else value)
    return output.getvalue()


def _valid_files() -> dict[str, str]:
    return {
        "weclever_rag_knowledge/README.md": "Package notes",
        "weclever_rag_knowledge/collection_manifest.json": json.dumps({"name": "WeClever"}),
        "weclever_rag_knowledge/weclever-domain/reference_tables.md": "# Reference tables",
        "weclever_rag_knowledge/weclever-domain/domain_taxonomy.json": '{"domain": "billing"}',
        "weclever_rag_knowledge/weclever-api/api_knowledge.jsonl": '{"content":"Call API","method":"POST"}\n',
    }


def test_valid_zip_manifest_root_nested_paths_and_readme(tmp_path: Path) -> None:
    importer = KnowledgePackageImporter(_service(tmp_path))
    plan = importer.inspect_zip(kb_id="KB1", payload=_zip(_valid_files()), filename="weclever.zip")

    assert plan.can_execute is True
    assert plan.package_root == "weclever_rag_knowledge"
    assert plan.manifest_metadata == {"name": "WeClever"}
    assert {item.collection_id for item in plan.collections} == {"weclever-api", "weclever-domain"}
    domain = next(item for item in plan.collections if item.collection_id == "weclever-domain")
    assert {item.relative_path for item in domain.documents} == {"domain_taxonomy.json", "reference_tables.md"}
    assert any("Root README ignored" in warning for warning in plan.warnings)


def test_valid_folder_upload_and_missing_manifest(tmp_path: Path) -> None:
    importer = KnowledgePackageImporter(_service(tmp_path))
    plan = importer.inspect_folder_upload(
        kb_id="KB1",
        files=[
            ("package/domain/guide.md", b"Guide"),
            ("package/rules/rules.txt", b"Rule"),
        ],
    )

    assert plan.package_root == "package"
    assert plan.manifest_metadata == {}
    assert {item.collection_id for item in plan.collections} == {"domain", "rules"}


def test_empty_collection_unsupported_file_and_hidden_artifacts(tmp_path: Path) -> None:
    payload = _zip(
        {
            "weclever_rag_knowledge/domain/.DS_Store": "ignored",
            "weclever_rag_knowledge/domain/image.png": b"png",
            "weclever_rag_knowledge/__MACOSX/noise.txt": "ignored",
            "weclever_rag_knowledge/Thumbs.db": "ignored",
        },
        directories=(
            "weclever_rag_knowledge/",
            "weclever_rag_knowledge/domain/",
            "weclever_rag_knowledge/empty-collection/",
        ),
    )
    plan = KnowledgePackageImporter(_service(tmp_path)).inspect_zip(
        kb_id="KB1", payload=payload, filename="package.zip"
    )

    empty = next(item for item in plan.collections if item.collection_id == "empty-collection")
    unsupported = next(item for item in plan.documents if item.original_filename == "image.png")
    assert "Collection directory is empty." in empty.warnings
    assert unsupported.supported is False
    assert unsupported.action == "skip"
    assert len(plan.documents) == 1


@pytest.mark.parametrize("folder", ["!!!", "a"])
def test_invalid_collection_name_is_reported(tmp_path: Path, folder: str) -> None:
    payload = _zip({f"root/{folder}/guide.md": "Guide"}, directories=("root/",))
    plan = KnowledgePackageImporter(_service(tmp_path)).inspect_zip(
        kb_id="KB1", payload=payload, filename="package.zip"
    )
    assert any(item["code"] == "invalid_collection_id" for item in plan.fatal_errors)
    assert plan.can_execute is False


def test_normalized_collection_collision_blocks_import(tmp_path: Path) -> None:
    payload = _zip(
        {"root/A B/one.md": "One", "root/a-b/two.md": "Two"},
        directories=("root/",),
    )
    plan = KnowledgePackageImporter(_service(tmp_path)).inspect_zip(
        kb_id="KB1", payload=payload, filename="package.zip"
    )
    assert any(item["code"] == "duplicate_collection_id" for item in plan.fatal_errors)


def test_document_ids_are_deterministic_nested_and_collision_safe(tmp_path: Path) -> None:
    files = {
        "root/cases/billing/payment.jsonl": '{"content":"one"}',
        "root/cases/billing payment.jsonl": '{"content":"two"}',
    }
    importer = KnowledgePackageImporter(_service(tmp_path))
    first = importer.inspect_zip(kb_id="KB1", payload=_zip(files, directories=("root/",)), filename="p.zip")
    second = importer.inspect_zip(kb_id="KB1", payload=_zip(files, directories=("root/",)), filename="p.zip")
    first_ids = [item.document_id for item in first.documents]
    assert first_ids == [item.document_id for item in second.documents]
    assert len(first_ids) == len(set(first_ids)) == 2
    assert any(item.startswith("billing-payment") for item in first_ids)
    assert any("stable checksum" in warning for warning in first.warnings)


def test_existing_collection_and_document_conflicts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_collection("KB1", "domain", "Domain", "", 100, "tester")
    service.upload_document(
        kb_id="KB1", collection_id="domain", document_id="guide", title="Guide",
        source_type="manual", external_id=None, confidence=1.0, effective_from=None,
        effective_to=None, raw_content=b"Old", extension=".md", actor="tester",
    )
    payload = _zip({"root/domain/guide.md": "New"}, directories=("root/",))
    importer = KnowledgePackageImporter(service)
    skip = importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip", conflict_mode="skip")
    fail = importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip", conflict_mode="fail")
    assert skip.collections[0].action == "reuse"
    assert skip.documents[0].action == "skip"
    assert skip.can_execute is True
    assert fail.can_execute is False


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "C:/absolute.md", "root/../escape.md"])
def test_zip_path_security_rejects_traversal_and_absolute_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(KnowledgePackageSecurityError):
        KnowledgePackageImporter(_service(tmp_path)).inspect_zip(
            kb_id="KB1", payload=_zip({path: "bad"}, directories=()), filename="p.zip"
        )


def test_zip_symbolic_link_is_rejected(tmp_path: Path) -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        info = ZipInfo("root/domain/link.md")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with pytest.raises(KnowledgePackageSecurityError, match="Symbolic links"):
        KnowledgePackageImporter(_service(tmp_path)).inspect_zip(
            kb_id="KB1", payload=output.getvalue(), filename="p.zip"
        )


def test_package_file_count_total_size_depth_and_manual_file_size_isolation(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path)
    importer = KnowledgePackageImporter(service)
    monkeypatch.setenv("KB_PACKAGE_MAX_FILE_COUNT", "1")
    with pytest.raises(KnowledgePackageSecurityError, match="file count"):
        importer.inspect_zip(kb_id="KB1", payload=_zip({"r/a/a.md": "a", "r/a/b.md": "b"}), filename="p.zip")

    monkeypatch.setenv("KB_PACKAGE_MAX_FILE_COUNT", "10")
    monkeypatch.setenv("KB_PACKAGE_MAX_UNCOMPRESSED_SIZE_BYTES", "1024")
    with pytest.raises(KnowledgePackageSecurityError, match="uncompressed size"):
        importer.inspect_zip(kb_id="KB1", payload=_zip({"r/a/a.md": "x" * 2048}), filename="p.zip")

    monkeypatch.setenv("KB_PACKAGE_MAX_UNCOMPRESSED_SIZE_BYTES", "10000")
    monkeypatch.setenv("KB_PACKAGE_MAX_DIRECTORY_DEPTH", "2")
    with pytest.raises(KnowledgePackageSecurityError, match="directory depth"):
        importer.inspect_zip(kb_id="KB1", payload=_zip({"r/a/b/c/d.md": "x"}), filename="p.zip")

    monkeypatch.setenv("KB_PACKAGE_MAX_DIRECTORY_DEPTH", "12")
    monkeypatch.setenv("KNOWLEDGE_BASE_MAX_FILE_SIZE_BYTES", "1024")
    package_plan = importer.inspect_zip(
        kb_id="KB1",
        payload=_zip({"r/domain/large.md": "x" * 2048}, directories=("r/",)),
        filename="p.zip",
    )
    assert package_plan.can_execute is True
    assert importer.execute_import(package_plan)["status"] == "completed"

    with pytest.raises(KnowledgeValidationError, match="File size exceeds"):
        service.upload_document(
            kb_id="KB1", collection_id="domain", document_id="manual-large",
            title="Manual", source_type="manual", external_id=None, confidence=1.0,
            effective_from=None, effective_to=None, raw_content=b"x" * 2048,
            extension=".md", actor="tester",
        )


def test_compressed_size_ratio_and_malformed_archive_limits(tmp_path: Path, monkeypatch) -> None:
    importer = KnowledgePackageImporter(_service(tmp_path))
    monkeypatch.setenv("KB_PACKAGE_MAX_COMPRESSION_RATIO", "2")
    bomb = _zip({"root/domain/repeated.txt": "a" * 10000}, compression=ZIP_DEFLATED)
    with pytest.raises(KnowledgePackageSecurityError, match="compression ratio"):
        importer.inspect_zip(kb_id="KB1", payload=bomb, filename="p.zip")

    monkeypatch.setenv("KB_PACKAGE_MAX_COMPRESSED_SIZE_BYTES", "1024")
    with pytest.raises(KnowledgePackageSecurityError, match="compressed size"):
        importer.inspect_zip(kb_id="KB1", payload=b"x" * 1025, filename="p.zip")

    monkeypatch.setenv("KB_PACKAGE_MAX_COMPRESSED_SIZE_BYTES", "1000")
    with pytest.raises(KnowledgePackageError, match="Malformed"):
        importer.inspect_zip(kb_id="KB1", payload=b"not-a-zip", filename="p.zip")


def test_execute_creates_collections_uploads_documents_and_audits(tmp_path: Path) -> None:
    service = _service(tmp_path)
    importer = KnowledgePackageImporter(service)
    plan = importer.inspect_zip(kb_id="KB1", payload=_zip(_valid_files()), filename="weclever.zip")
    result = importer.execute_import(plan)

    assert result["status"] == "completed"
    assert len(service.list_collections("KB1")) == 2
    assert len(service.list_documents("KB1")) == 3
    assert all(item.status == DocumentStatus.READY_FOR_REVIEW for item in service.list_documents("KB1"))
    assert all(item.source_type == "knowledge-package" for item in service.list_documents("KB1"))
    assert any("reference_tables.md" in (item.external_id or "") for item in service.list_documents("KB1"))
    assert service.audit("KB1")[-1]["event"] == "knowledge_package_imported"


def test_fail_mode_dry_run_and_repeated_skip_are_non_destructive(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_collection("KB1", "weclever-domain", "Domain", "", 100, "tester")
    importer = KnowledgePackageImporter(service)
    payload = _zip(_valid_files())
    failed_plan = importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip", conflict_mode="fail")
    assert importer.execute_import(failed_plan)["status"] == "blocked"
    assert service.list_documents("KB1") == []

    first = importer.execute_import(importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip"))
    second = importer.execute_import(importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip"))
    assert first["status"] == "completed"
    assert all(item["status"] in {"reuse", "skip"} for item in second["collections"] + second["documents"])
    assert len(service.list_documents("KB1")) == 3


def test_auto_publish_is_explicit_and_partial_failures_are_reported(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path)
    importer = KnowledgePackageImporter(service)
    payload = _zip({"root/domain/one.md": "One", "root/domain/two.md": "Two"}, directories=("root/",))
    plan = importer.inspect_zip(kb_id="KB1", payload=payload, filename="p.zip")
    original_upload = service.ingest_package_document

    def flaky_upload(**kwargs):
        if kwargs["document_id"] == "two":
            raise RuntimeError("storage down")
        return original_upload(**kwargs)

    monkeypatch.setattr(service, "ingest_package_document", flaky_upload)
    result = importer.execute_import(plan, auto_publish=True)
    assert result["status"] == "completed_with_errors"
    assert {item["status"] for item in result["documents"]} == {"published", "failed"}
    assert service.get_document("KB1", "one").status == DocumentStatus.INDEXED
    assert "storage down" not in json.dumps(result)


def test_jsonl_package_is_consumed_record_by_record(tmp_path: Path) -> None:
    class NoWholeFileRead(BytesIO):
        def read(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                raise AssertionError("whole-file read is forbidden")
            return super().read(size)

        def read1(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                raise AssertionError("whole-file read is forbidden")
            return super().read(size)

    service = _service(tmp_path)
    importer = KnowledgePackageImporter(service)
    payload = b"".join(
        json.dumps({"content": f"record {index}"}).encode("utf-8") + b"\n"
        for index in range(250)
    )
    stream = NoWholeFileRead(payload)
    plan = importer.inspect_folder_streams(
        kb_id="KB1",
        files=[("package/domain/records.jsonl", stream, len(payload))],
    )

    assert plan.documents[0].size_bytes == len(payload)
    assert plan.documents[0].supported is True
    assert importer.execute_import(plan, auto_publish=True)["status"] == "completed"
    assert service.get_document("KB1", "records").parsing_preview["chunk_count"] == 250


def test_representative_weclever_package_detects_seven_collections(tmp_path: Path) -> None:
    names = [
        "weclever-domain", "weclever-business-rules", "weclever-api",
        "weclever-integrations", "weclever-test-cases", "weclever-defects",
        "weclever-project-guidelines",
    ]
    files = {f"weclever_rag_knowledge/{name}/document-{index}.md": f"Content {index}" for index, name in enumerate(names)}
    files["weclever_rag_knowledge/collection_manifest.json"] = "{}"
    service = _service(tmp_path)
    importer = KnowledgePackageImporter(service)
    plan = importer.inspect_zip(kb_id="KB1", payload=_zip(files), filename="weclever.zip")
    result = importer.execute_import(plan)
    assert plan.to_dict()["collection_count"] == 7
    assert plan.to_dict()["document_count"] == 7
    assert len(service.list_collections("KB1")) == 7
    assert len(service.list_documents("KB1")) == 7
    assert result["status"] == "completed"
