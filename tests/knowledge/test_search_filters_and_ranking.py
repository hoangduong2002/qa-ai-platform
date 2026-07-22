from __future__ import annotations

from pathlib import Path

from knowledge.domain.models import SearchRequest
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _setup(tmp_path: Path) -> KnowledgeServiceFacade:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "KB One", "", "tester")
    service.create_collection("KB1", "domain", "Domain", "", 10, "tester")
    service.create_collection("KB1", "api", "API", "", 20, "tester")

    service.upload_document(
        kb_id="KB1",
        collection_id="domain",
        document_id="DOC1",
        title="Identifiers",
        source_type="manual",
        external_id="EXT-1",
        confidence=0.9,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-12-31T23:59:59Z",
        raw_content="HBLD090 requires CMU validation".encode("utf-8"),
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC1", "tester")

    service.upload_document(
        kb_id="KB1",
        collection_id="api",
        document_id="DOC2",
        title="Accent",
        source_type="manual",
        external_id="EXT-2",
        confidence=0.7,
        effective_from=None,
        effective_to=None,
        raw_content="cafe with accent cafe and caf\u00e9".encode("utf-8"),
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC2", "tester")

    return service


def test_collection_filter(tmp_path: Path) -> None:
    service = _setup(tmp_path)
    result = service.search("KB1", SearchRequest(query="validation", collection_id="domain", top_k=10))
    assert all(item.collection_id == "domain" for item in result.results)


def test_effective_date_filter(tmp_path: Path) -> None:
    service = _setup(tmp_path)
    result = service.search("KB1", SearchRequest(query="HBLD090", effective_at="2027-01-01T00:00:00Z", top_k=10))
    assert result.total == 0


def test_exact_identifier_search(tmp_path: Path) -> None:
    service = _setup(tmp_path)
    result = service.search("KB1", SearchRequest(query="HBLD090", top_k=5))
    assert result.total >= 1
    assert "HBLD090" in result.results[0].content


def test_accent_handling(tmp_path: Path) -> None:
    service = _setup(tmp_path)
    result = service.search("KB1", SearchRequest(query="cafe", top_k=5))
    assert result.total >= 1


def test_superseded_documents_excluded_from_search(tmp_path: Path) -> None:
    service = _setup(tmp_path)

    service.upload_document(
        kb_id="KB1",
        collection_id="domain",
        document_id="DOC3",
        title="Replacement",
        source_type="manual",
        external_id="EXT-3",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"Replacement content",
        extension=".txt",
        actor="tester",
    )
    service.publish_document("KB1", "DOC3", "tester")
    service.supersede_document("KB1", "DOC1", "DOC3", "tester")

    result = service.search("KB1", SearchRequest(query="HBLD090", top_k=10))
    assert all(item.document_id != "DOC1" for item in result.results)
