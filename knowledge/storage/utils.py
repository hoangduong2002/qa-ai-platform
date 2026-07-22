from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from knowledge.domain.errors import KnowledgeValidationError


VALID_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$")


def validate_identifier(value: str, label: str) -> str:
    value = (value or "").strip()

    if not VALID_ID_RE.match(value):
        raise KnowledgeValidationError(
            f"Invalid {label}. Only letters, digits, _, -, . are allowed and length must be 2-128."
        )

    return value


def safe_child(root: Path, *parts: str) -> Path:
    current = root.resolve()

    for part in parts:
        if part in {"", ".", ".."}:
            raise KnowledgeValidationError("Invalid path segment.")

        if any(token in part for token in ("..", "\\", "/", "\x00")):
            raise KnowledgeValidationError("Path traversal detected.")

        current = (current / part).resolve()

        if root.resolve() not in [current, *current.parents]:
            raise KnowledgeValidationError("Path traversal detected.")

    return current


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as temp_file:
        temp_file.write(content)
        temp_name = temp_file.name

    last_error = None

    for _ in range(5):
        try:
            os.replace(temp_name, path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.05)

    if last_error:
        raise last_error


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def content_checksum(raw_content: bytes) -> str:
    return hashlib.sha256(raw_content).hexdigest()
