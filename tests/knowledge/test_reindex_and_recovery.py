from __future__ import annotations

import threading
from pathlib import Path

from knowledge.domain.models import SearchRequest
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _prepare(tmp_path: Path) -> KnowledgeServiceFacade:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "KB One", "", "tester")
    service.create_collection("KB1", "domain", "Domain", "", 10, "tester")
    service.upload_document(
        kb_id="KB1",
        collection_id="domain",
        document_id="DOC1",
        title="Doc1",
        source_type="manual",
        external_id="EXT-1",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"ABC token",
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC1", "tester")
    return service


def test_reindex_while_search_uses_old_index(tmp_path: Path) -> None:
    service = _prepare(tmp_path)

    errors: list[str] = []

    def reader():
        try:
            for _ in range(25):
                service.search("KB1", SearchRequest(query="ABC", top_k=2))
        except Exception as error:
            errors.append(str(error))

    thread = threading.Thread(target=reader)
    thread.start()
    service.reindex("KB1", actor="tester")
    thread.join()

    assert not errors


def test_corrupted_index_recovery(tmp_path: Path) -> None:
    service = _prepare(tmp_path)
    db_path = service.storage.index_db_path("KB1")
    db_path.write_bytes(b"not a sqlite db")

    service.reindex("KB1", actor="tester")
    result = service.search("KB1", SearchRequest(query="ABC", top_k=5))
    assert result.total >= 1


def test_recover_interrupted_publish_state(tmp_path: Path) -> None:
    service = _prepare(tmp_path)
    service.storage.update_document("KB1", "DOC1", {"status": "PUBLISHING"})

    recovery = service.recover("KB1", actor="tester")
    assert "DOC1" in recovery["recovered_documents"]
    assert service.get_document("KB1", "DOC1").status.value == "FAILED"
