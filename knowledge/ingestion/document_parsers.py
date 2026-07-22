from __future__ import annotations

import json

from markdown_it import MarkdownIt

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.domain.protocols import DocumentParser


class MarkdownDocumentParser(DocumentParser):
    def supports_extension(self, extension: str) -> bool:
        return extension.lower() in {".md", ".markdown"}

    def parse(self, content: str) -> list[str]:
        # Parse once to validate markdown tokenization; chunks remain text-first.
        MarkdownIt().parse(content)
        return _split_text(content)


class JsonDocumentParser(DocumentParser):
    def supports_extension(self, extension: str) -> bool:
        return extension.lower() == ".json"

    def parse(self, content: str) -> list[str]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise KnowledgeValidationError(f"Malformed JSON: {error}") from error

        if isinstance(payload, dict):
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return _split_text(text)

        if isinstance(payload, list):
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return _split_text(text)

        raise KnowledgeValidationError("JSON payload must be object or array.")


class JsonlDocumentParser(DocumentParser):
    def supports_extension(self, extension: str) -> bool:
        return extension.lower() == ".jsonl"

    def parse(self, content: str) -> list[str]:
        lines = [line for line in content.splitlines() if line.strip()]

        if not lines:
            raise KnowledgeValidationError("JSONL content is empty.")

        parsed_lines: list[str] = []

        for index, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise KnowledgeValidationError(f"Malformed JSONL at line {index}: {error}") from error

            parsed_lines.append(json.dumps(value, ensure_ascii=False))

        return _split_text("\n".join(parsed_lines))


class TextDocumentParser(DocumentParser):
    def supports_extension(self, extension: str) -> bool:
        return extension.lower() in {".txt", ".log", ".text"}

    def parse(self, content: str) -> list[str]:
        return _split_text(content)


def _split_text(content: str, max_chars: int = 1200) -> list[str]:
    normalized = (content or "").strip()

    if not normalized:
        raise KnowledgeValidationError("Document content is empty.")

    chunks: list[str] = []

    for start in range(0, len(normalized), max_chars):
        part = normalized[start : start + max_chars].strip()
        if part:
            chunks.append(part)

    if not chunks:
        raise KnowledgeValidationError("Document content is empty.")

    return chunks
