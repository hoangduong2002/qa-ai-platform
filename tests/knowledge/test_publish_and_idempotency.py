from __future__ import annotations

from pathlib import Path

from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _service(tmp_path: Path) -> KnowledgeServiceFacade:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "KB One", "", "tester")
    service.create_collection("KB1", "business-rules", "Business Rules", "", 10, "tester")
    return service


def test_double_publish_returns_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)

    service.upload_document(
        kb_id="KB1",
        collection_id="business-rules",
        document_id="DOC1",
        title="Rules",
        source_type="manual",
        external_id="EXT-1",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"Rule A\nRule B",
        extension=".txt",
        actor="tester",
    )

    first = service.publish_document("KB1", "DOC1", "tester")
    second = service.publish_document("KB1", "DOC1", "tester")

    assert first["status"] == "published"
    assert second["status"] == "idempotent"


def test_idempotent_publish_by_checksum(tmp_path: Path) -> None:
    service = _service(tmp_path)

    service.upload_document(
        kb_id="KB1",
        collection_id="business-rules",
        document_id="DOC1",
        title="Rules",
        source_type="manual",
        external_id="EXT-1",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"Rule A",
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC1", "tester")

    result = service.publish_document("KB1", "DOC1", "tester")
    assert result["status"] == "idempotent"
