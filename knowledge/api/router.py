from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from knowledge.api.deps import require_kb_enabled, require_maintainer
from knowledge.domain.models import SearchRequest, utc_now_iso
from knowledge.services.runtime import get_knowledge_service


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


@router.get("/health")
def kb_feature_health(_: None = Depends(require_kb_enabled)):
    service = get_knowledge_service()
    return {
        "enabled": True,
        "fts5_supported": service.retriever.verify_fts5(),
    }


@router.post("/bases")
def create_kb(
    kb_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    service = get_knowledge_service()
    return service.create_kb(kb_id, name, description, actor="maintainer").model_dump()


@router.get("/bases")
def list_kbs(_: None = Depends(require_kb_enabled)):
    service = get_knowledge_service()
    return [item.model_dump() for item in service.list_kbs()]


@router.get("/bases/{kb_id}")
def get_kb(kb_id: str, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().get_kb(kb_id).model_dump()


@router.patch("/bases/{kb_id}")
def update_kb(
    kb_id: str,
    name: str | None = Form(None),
    description: str | None = Form(None),
    enabled: bool | None = Form(None),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    patch = {"updated_at": utc_now_iso()}
    if name is not None:
        patch["name"] = name
    if description is not None:
        patch["description"] = description
    if enabled is not None:
        patch["enabled"] = enabled
    return get_knowledge_service().update_kb(kb_id, patch, actor="maintainer").model_dump()


@router.get("/bases/{kb_id}/health")
def kb_health(kb_id: str, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().kb_health(kb_id)


@router.post("/bases/{kb_id}/collections")
def create_collection(
    kb_id: str,
    collection_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    priority: int = Form(100),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().create_collection(
        kb_id,
        collection_id,
        name,
        description,
        priority,
        actor="maintainer",
    ).model_dump()


@router.get("/bases/{kb_id}/collections")
def list_collections(kb_id: str, _: None = Depends(require_kb_enabled)):
    return [item.model_dump() for item in get_knowledge_service().list_collections(kb_id)]


@router.patch("/bases/{kb_id}/collections/{collection_id}")
def update_collection(
    kb_id: str,
    collection_id: str,
    name: str | None = Form(None),
    description: str | None = Form(None),
    archived: bool | None = Form(None),
    priority: int | None = Form(None),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    patch = {}
    if name is not None:
        patch["name"] = name
    if description is not None:
        patch["description"] = description
    if archived is not None:
        patch["archived"] = archived
    if priority is not None:
        patch["priority"] = priority

    return get_knowledge_service().update_collection(kb_id, collection_id, patch, actor="maintainer").model_dump()


@router.post("/bases/{kb_id}/documents/upload")
async def upload_document(
    kb_id: str,
    collection_id: str = Form(...),
    document_id: str = Form(...),
    title: str = Form(...),
    source_type: str = Form("manual"),
    external_id: str = Form(""),
    confidence: float = Form(1.0),
    effective_from: str = Form(""),
    effective_to: str = Form(""),
    file: UploadFile = File(...),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    raw = await file.read()
    document = get_knowledge_service().upload_document(
        kb_id=kb_id,
        collection_id=collection_id,
        document_id=document_id,
        title=title,
        source_type=source_type,
        external_id=external_id or None,
        confidence=confidence,
        effective_from=effective_from or None,
        effective_to=effective_to or None,
        raw_content=raw,
        extension=("." + file.filename.split(".")[-1].lower()) if file.filename and "." in file.filename else ".txt",
        actor="maintainer",
    )
    return document.model_dump()


@router.get("/bases/{kb_id}/documents")
def list_documents(kb_id: str, collection_id: str | None = None, _: None = Depends(require_kb_enabled)):
    return [item.model_dump() for item in get_knowledge_service().list_documents(kb_id, collection_id)]


@router.get("/bases/{kb_id}/documents/{document_id}/preview")
def preview_document(kb_id: str, document_id: str, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().get_document(kb_id, document_id).parsing_preview


@router.post("/bases/{kb_id}/documents/{document_id}/publish")
def publish_document(
    kb_id: str,
    document_id: str,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().publish_document(kb_id, document_id, actor="maintainer")


@router.post("/bases/{kb_id}/documents/{document_id}/retry-publish")
def retry_publish(
    kb_id: str,
    document_id: str,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().retry_publish(kb_id, document_id, actor="maintainer")


@router.post("/bases/{kb_id}/documents/{document_id}/archive")
def archive_document(
    kb_id: str,
    document_id: str,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().archive_document(kb_id, document_id, actor="maintainer").model_dump()


@router.post("/bases/{kb_id}/documents/{document_id}/supersede")
def supersede_document(
    kb_id: str,
    document_id: str,
    replacement_document_id: str = Form(...),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().supersede_document(kb_id, document_id, replacement_document_id, actor="maintainer")


@router.post("/bases/{kb_id}/search")
def search(kb_id: str, request: SearchRequest, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().search(kb_id, request).model_dump()


@router.post("/bases/{kb_id}/reindex")
def reindex(
    kb_id: str,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    return get_knowledge_service().reindex(kb_id, actor="maintainer")


@router.get("/bases/{kb_id}/audit")
def audit(kb_id: str, limit: int = 100, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().audit(kb_id, limit=limit)
