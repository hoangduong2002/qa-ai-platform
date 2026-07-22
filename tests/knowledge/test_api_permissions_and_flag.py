from __future__ import annotations

import pytest
from fastapi import HTTPException

from knowledge.api.deps import require_kb_enabled, require_maintainer


def test_permission_enforcement(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "secret")

    with pytest.raises(HTTPException):
        require_maintainer("wrong")


def test_disabled_feature_flag(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "false")

    with pytest.raises(HTTPException):
        require_kb_enabled()
