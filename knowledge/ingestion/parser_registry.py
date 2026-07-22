from __future__ import annotations

from charset_normalizer import from_bytes

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.domain.protocols import DocumentParser
from knowledge.ingestion.document_parsers import (
    JsonDocumentParser,
    JsonlDocumentParser,
    MarkdownDocumentParser,
    TextDocumentParser,
)


class ParserRegistry:
    def __init__(self):
        self.parsers: list[DocumentParser] = [
            MarkdownDocumentParser(),
            JsonDocumentParser(),
            JsonlDocumentParser(),
            TextDocumentParser(),
        ]

    def parser_for(self, extension: str) -> DocumentParser:
        for parser in self.parsers:
            if parser.supports_extension(extension):
                return parser

        raise KnowledgeValidationError(f"Unsupported format: {extension}")

    def decode_bytes(self, payload: bytes) -> str:
        best = from_bytes(payload).best()

        if best is None or not best.encoding:
            raise KnowledgeValidationError("Invalid or unsupported text encoding.")

        try:
            return str(best)
        except Exception as error:
            raise KnowledgeValidationError("Invalid or unsupported text encoding.") from error
