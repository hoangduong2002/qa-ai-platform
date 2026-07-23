from __future__ import annotations

import json
from typing import NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from knowledge.api.deps import require_kb_enabled, require_maintainer
from knowledge.domain.models import SearchRequest
from knowledge.services.runtime import get_knowledge_service
from knowledge.domain.errors import (
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgePackageError,
    KnowledgePackageSecurityError,
    KnowledgeValidationError,
)
from knowledge.services.package_importer import KnowledgePackageImporter


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


async def _request_payload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError as error:
            raise KnowledgeValidationError("Request body contains invalid JSON.") from error
        if not isinstance(payload, dict):
            raise KnowledgeValidationError("Request body must be a JSON object.")
        return payload
    form = await request.form()
    payload = dict(form)
    if "jira_project_keys" in form:
        payload["jira_project_keys"] = form.getlist("jira_project_keys")
    return payload


def _jira_project_keys_from_value(value) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, str) for item in values):
        raise KnowledgeValidationError("Jira project keys must be strings.")
    if len(values) == 1 and not values[0].strip():
        return []
    return [part for item in values for part in item.split(",")]


def _optional_bool(value):
    if value is None or isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise KnowledgeValidationError("Invalid enabled value.")


def _raise_kb_http_error(error: Exception) -> NoReturn:
    if isinstance(error, KnowledgeConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, KnowledgeNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, KnowledgeValidationError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise error


@router.get("/health")
def kb_feature_health(_: None = Depends(require_kb_enabled)):
    service = get_knowledge_service()
    return {
        "enabled": True,
        "fts5_supported": service.retriever.verify_fts5(),
    }


@router.post("/bases")
async def create_kb(
    request: Request,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    try:
        payload = await _request_payload(request)
        service = get_knowledge_service()
        return service.create_kb(
            str(payload.get("kb_id") or ""),
            str(payload.get("name") or ""),
            str(payload.get("description") or ""),
            actor="maintainer",
            jira_project_keys=_jira_project_keys_from_value(payload.get("jira_project_keys")),
        ).model_dump()
    except (KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeValidationError) as error:
        _raise_kb_http_error(error)


@router.get("/bases")
def list_kbs(_: None = Depends(require_kb_enabled)):
    service = get_knowledge_service()
    return [item.model_dump() for item in service.list_kbs()]


@router.get("/bases/resolve")
def resolve_kb_by_jira_project_key(
    jira_project_key: str,
    _: None = Depends(require_kb_enabled),
):
    try:
        service = get_knowledge_service()
        normalized = service.normalize_jira_project_keys([jira_project_key])[0]
        kb = service.resolve_kb_by_jira_project_key(normalized)
        return {
            "jira_project_key": normalized,
            "resolved": kb is not None,
            "knowledge_base": None if kb is None else {
                "kb_id": kb.kb_id,
                "name": kb.name,
                "jira_project_keys": kb.jira_project_keys,
            },
        }
    except KnowledgeValidationError as error:
        _raise_kb_http_error(error)


@router.get("/bases/{kb_id}")
def get_kb(kb_id: str, _: None = Depends(require_kb_enabled)):
    return get_knowledge_service().get_kb(kb_id).model_dump()


@router.patch("/bases/{kb_id}")
async def update_kb(
    kb_id: str,
    request: Request,
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    try:
        payload = await _request_payload(request)
        patch = {}
        if "name" in payload:
            patch["name"] = payload["name"]
        if "description" in payload:
            patch["description"] = payload["description"]
        if "enabled" in payload:
            patch["enabled"] = _optional_bool(payload["enabled"])
        if "jira_project_keys" in payload:
            patch["jira_project_keys"] = _jira_project_keys_from_value(
                payload["jira_project_keys"]
            )
        return get_knowledge_service().update_kb(
            kb_id, patch, actor="maintainer"
        ).model_dump()
    except (KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeValidationError) as error:
        _raise_kb_http_error(error)


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


async def _inspect_package_upload(
    *,
    kb_id: str,
    conflict_mode: str,
    zip_file: UploadFile | None,
    folder_files: list[UploadFile],
):
    importer = KnowledgePackageImporter(get_knowledge_service())
    if zip_file and zip_file.filename:
        return importer.inspect_zip_stream(
            kb_id=kb_id,
            stream=zip_file.file,
            filename=zip_file.filename,
            conflict_mode=conflict_mode,
            compressed_size=importer._stream_size(zip_file.file),
        )
    if folder_files:
        files = [
            (item.filename or "", item.file, importer._stream_size(item.file))
            for item in folder_files
            if item.filename
        ]
        return importer.inspect_folder_streams(
            kb_id=kb_id,
            files=files,
            package_name="folder-upload",
            conflict_mode=conflict_mode,
        )
    raise HTTPException(status_code=400, detail="Select a ZIP package or folder files.")


@router.post("/bases/{kb_id}/packages/inspect")
async def inspect_knowledge_package(
    kb_id: str,
    conflict_mode: str = Form("skip"),
    zip_file: UploadFile | None = File(None),
    folder_files: list[UploadFile] = File(default=[]),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    try:
        plan = await _inspect_package_upload(
            kb_id=kb_id,
            conflict_mode=conflict_mode,
            zip_file=zip_file,
            folder_files=folder_files,
        )
        return plan.to_dict()
    except KnowledgePackageSecurityError as error:
        raise HTTPException(status_code=400, detail={"code": "archive_security_violation", "message": str(error)}) from error
    except KnowledgePackageError as error:
        raise HTTPException(status_code=400, detail={"code": "package_validation_failed", "message": str(error)}) from error


@router.post("/bases/{kb_id}/packages/import")
async def import_knowledge_package(
    kb_id: str,
    conflict_mode: str = Form("skip"),
    auto_publish: bool = Form(False),
    dry_run: bool = Form(False),
    zip_file: UploadFile | None = File(None),
    folder_files: list[UploadFile] = File(default=[]),
    _: None = Depends(require_kb_enabled),
    __: None = Depends(require_maintainer),
):
    try:
        plan = await _inspect_package_upload(
            kb_id=kb_id,
            conflict_mode=conflict_mode,
            zip_file=zip_file,
            folder_files=folder_files,
        )
        if dry_run:
            return {"status": "dry_run", "plan": plan.to_dict()}
        if not plan.can_execute:
            raise HTTPException(status_code=409, detail={"code": "package_conflict", "plan": plan.to_dict()})
        return KnowledgePackageImporter(get_knowledge_service()).execute_import(
            plan,
            auto_publish=auto_publish,
            actor="maintainer",
        )
    except HTTPException:
        raise
    except KnowledgePackageSecurityError as error:
        raise HTTPException(status_code=400, detail={"code": "archive_security_violation", "message": str(error)}) from error
    except KnowledgePackageError as error:
        raise HTTPException(status_code=400, detail={"code": "package_validation_failed", "message": str(error)}) from error
