from __future__ import annotations

from pathlib import Path

import pytest

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def _service(tmp_path: Path) -> KnowledgeServiceFacade:
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "KB One", "", "tester")
    service.create_collection("KB1", "domain", "Domain", "", 10, "tester")
    return service


def test_malformed_json_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(KnowledgeValidationError):
        service.upload_document(
            kb_id="KB1",
            collection_id="domain",
            document_id="DOC1",
            title="Broken JSON",
            source_type="manual",
            external_id="EXT-1",
            confidence=1.0,
            effective_from=None,
            effective_to=None,
            raw_content=b"{bad json",
            extension=".json",
            actor="tester",
        )


def test_duplicate_upload_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)

    service.upload_document(
        kb_id="KB1",
        collection_id="domain",
        document_id="DOC1",
        title="Doc One",
        source_type="manual",
        external_id="EXT-1",
        confidence=1.0,
        effective_from=None,
        effective_to=None,
        raw_content=b"same",
        extension=".txt",
        actor="tester",
    )

    with pytest.raises(KnowledgeValidationError):
        service.upload_document(
            kb_id="KB1",
            collection_id="domain",
            document_id="DOC2",
            title="Doc Two",
            source_type="manual",
            external_id="EXT-2",
            confidence=1.0,
            effective_from=None,
            effective_to=None,
            raw_content=b"same",
            extension=".txt",
            actor="tester",
        )
