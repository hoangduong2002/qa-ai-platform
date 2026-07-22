from __future__ import annotations

from pathlib import Path

import pytest

from knowledge.services.knowledge_services import KnowledgeServiceFacade


def test_failed_publish_keeps_previous_index(tmp_path: Path, monkeypatch) -> None:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "KB One", "", "tester")
    service.create_collection("KB1", "business-rules", "Business Rules", "", 10, "tester")

    service.upload_document(
        kb_id="KB1",
        collection_id="business-rules",
        document_id="DOC1",
        title="Rules One",
        source_type="manual",
        external_id="EXT-1",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"first content",
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC1", "tester")
    index_before = service.storage.index_db_path("KB1").read_bytes()

    service.upload_document(
        kb_id="KB1",
        collection_id="business-rules",
        document_id="DOC2",
        title="Rules Two",
        source_type="manual",
        external_id="EXT-2",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"second content",
        extension=".txt",
        actor="tester",
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("forced rebuild failure")

    monkeypatch.setattr(service.retriever, "rebuild_index", _boom)

    with pytest.raises(RuntimeError):
        service.publish_document("KB1", "DOC2", "tester")

    index_after = service.storage.index_db_path("KB1").read_bytes()
    assert index_before == index_after
    assert service.get_document("KB1", "DOC2").status.value == "FAILED"
