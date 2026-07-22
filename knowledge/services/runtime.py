from __future__ import annotations

from knowledge.services.config import knowledge_base_root
from knowledge.services.knowledge_services import KnowledgeServiceFacade


_service: KnowledgeServiceFacade | None = None


def get_knowledge_service() -> KnowledgeServiceFacade:
    global _service

    if _service is None:
        _service = KnowledgeServiceFacade(knowledge_base_root())

    return _service
