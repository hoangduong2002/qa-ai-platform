from __future__ import annotations

from fastapi import Header, HTTPException

from knowledge.services.config import knowledge_base_enabled, maintainer_token


def require_kb_enabled() -> None:
    if not knowledge_base_enabled():
        raise HTTPException(status_code=404, detail="Knowledge Base feature is disabled.")


def require_maintainer(x_maintainer_token: str = Header(default="")) -> None:
    token = maintainer_token()

    if not token:
        raise HTTPException(
            status_code=503,
            detail="KNOWLEDGE_BASE_MAINTAINER_TOKEN is not configured.",
        )

    if x_maintainer_token != token:
        raise HTTPException(status_code=403, detail="Maintainer token is invalid.")
