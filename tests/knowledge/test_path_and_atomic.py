from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.storage.utils import atomic_write_json, safe_child, validate_identifier


def test_validate_identifier_rejects_path_traversal() -> None:
    with pytest.raises(KnowledgeValidationError):
        validate_identifier("../evil", "kb_id")


def test_safe_child_blocks_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()

    with pytest.raises(KnowledgeValidationError):
        safe_child(root, "..", "x")


def test_atomic_write_json_replaces_content(tmp_path: Path) -> None:
    file_path = tmp_path / "a.json"
    atomic_write_json(file_path, {"v": 1})
    atomic_write_json(file_path, {"v": 2})

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    assert payload["v"] == 2
