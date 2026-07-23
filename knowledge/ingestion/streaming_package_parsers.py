from __future__ import annotations

import json
from contextlib import contextmanager
from io import TextIOWrapper
from typing import BinaryIO, Iterator

from knowledge.domain.errors import KnowledgeValidationError


class StreamingPackageParserRegistry:
    """Package-only parsers that avoid whole-file reads for streamable formats."""

    _TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".log", ".text"}
    _SUPPORTED_EXTENSIONS = _TEXT_EXTENSIONS | {".json", ".jsonl"}

    def supports_extension(self, extension: str) -> bool:
        return extension.lower() in self._SUPPORTED_EXTENSIONS

    def validate_extension(self, extension: str) -> None:
        if not self.supports_extension(extension):
            raise KnowledgeValidationError(f"Unsupported format: {extension}")

    def inspect(self, stream: BinaryIO, extension: str) -> dict:
        samples: list[str] = []
        chunk_count = 0
        for chunk in self.iter_chunks(stream, extension):
            chunk_count += 1
            if len(samples) < 3:
                samples.append(chunk)
        if chunk_count == 0:
            raise KnowledgeValidationError("Document content is empty.")
        return {
            "valid": True,
            "chunk_count": chunk_count,
            "sample_chunks": samples,
            "warnings": [],
            "streaming": True,
        }

    def iter_chunks(self, stream: BinaryIO, extension: str, max_chars: int = 1200) -> Iterator[str]:
        extension = extension.lower()
        self.validate_extension(extension)
        if extension == ".jsonl":
            yield from self._iter_jsonl(stream, max_chars)
            return
        if extension == ".json":
            yield from self._iter_json(stream, max_chars)
            return
        yield from self._iter_text(stream, max_chars)

    @contextmanager
    def _text_reader(self, stream: BinaryIO):
        reader = TextIOWrapper(stream, encoding="utf-8-sig", errors="strict", newline="")
        try:
            yield reader
        except UnicodeDecodeError as error:
            raise KnowledgeValidationError("Invalid or unsupported text encoding.") from error
        finally:
            # Detach so closing the text wrapper never closes a ZIP member or
            # externally-owned upload stream before its context manager exits.
            try:
                reader.detach()
            except Exception:
                pass

    def _iter_jsonl(self, stream: BinaryIO, max_chars: int) -> Iterator[str]:
        found = False
        with self._text_reader(stream) as reader:
            for line_number, line in enumerate(reader, start=1):
                if not line.strip():
                    continue
                found = True
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise KnowledgeValidationError(
                        f"Malformed JSONL at line {line_number}: {error}"
                    ) from error
                if isinstance(value, dict) and "content" in value:
                    content = value["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise KnowledgeValidationError(
                            f"Malformed JSONL at line {line_number}: content must be a non-empty string."
                        )
                else:
                    content = json.dumps(value, ensure_ascii=False)
                yield from self._split_value(content, max_chars)
        if not found:
            raise KnowledgeValidationError("JSONL content is empty.")

    def _iter_json(self, stream: BinaryIO, max_chars: int) -> Iterator[str]:
        # The standard library has no incremental general JSON parser. This is
        # intentionally isolated to package JSON; JSONL remains fully streamed.
        with self._text_reader(stream) as reader:
            try:
                value = json.load(reader)
            except json.JSONDecodeError as error:
                raise KnowledgeValidationError(f"Malformed JSON: {error}") from error
        if not isinstance(value, (dict, list)):
            raise KnowledgeValidationError("JSON payload must be object or array.")
        yield from self._split_value(json.dumps(value, ensure_ascii=False, indent=2), max_chars)

    def _iter_text(self, stream: BinaryIO, max_chars: int) -> Iterator[str]:
        found = False
        with self._text_reader(stream) as reader:
            while True:
                value = reader.read(max_chars)
                if not value:
                    break
                value = value.strip()
                if value:
                    found = True
                    yield value
        if not found:
            raise KnowledgeValidationError("Document content is empty.")

    @staticmethod
    def _split_value(value: str, max_chars: int) -> Iterator[str]:
        normalized = (value or "").strip()
        if not normalized:
            raise KnowledgeValidationError("Document content is empty.")
        for start in range(0, len(normalized), max_chars):
            chunk = normalized[start : start + max_chars].strip()
            if chunk:
                yield chunk
