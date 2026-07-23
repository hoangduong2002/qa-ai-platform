from __future__ import annotations

import pytest

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.ingestion.document_parsers import JsonlDocumentParser


def test_jsonl_preserves_record_boundaries_and_extracts_content() -> None:
    chunks = JsonlDocumentParser().parse(
        '{"content":"First rule","priority":1}\n\n{"content":"Second rule","priority":2}\n'
    )
    assert chunks == ["First rule", "Second rule"]


def test_jsonl_non_content_record_remains_json() -> None:
    assert JsonlDocumentParser().parse('{"name":"rule","enabled":true}') == [
        '{"name": "rule", "enabled": true}'
    ]


def test_jsonl_malformed_line_reports_original_line_number() -> None:
    with pytest.raises(KnowledgeValidationError, match="line 3"):
        JsonlDocumentParser().parse('{"content":"ok"}\n\n{bad}')


def test_large_jsonl_does_not_become_one_opaque_chunk() -> None:
    content = "\n".join(f'{{"content":"record {index}"}}' for index in range(1000))
    chunks = JsonlDocumentParser().parse(content)
    assert len(chunks) == 1000
    assert chunks[0] == "record 0"
    assert chunks[-1] == "record 999"
