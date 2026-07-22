from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from knowledge.api.deps import require_kb_enabled
from knowledge.domain.models import SearchRequest
from knowledge.domain.errors import KnowledgeError
from knowledge.services.config import knowledge_base_enabled, maintainer_token
from knowledge.services.runtime import get_knowledge_service


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["knowledge_base_enabled"] = knowledge_base_enabled

router = APIRouter(prefix="/portal/kb", tags=["Knowledge Base UI"])


def _assert_ui_maintainer(provided_token: str) -> None:
    expected = maintainer_token()
    if not expected or provided_token != expected:
        raise KnowledgeError("Maintainer token is invalid for write operation.")


def _maintainer_error_message(error_code: str) -> str:
    if error_code == "maintainer_access_required":
        return "Maintainer access is required for this write operation. Check the configured token and try again."
    return ""


def _write_error_redirect(path: str) -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    query = urlencode({"error": "maintainer_access_required"})
    return RedirectResponse(url=f"{path}{separator}{query}", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def kb_list_page(
    request: Request,
    error: str = "",
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    return templates.TemplateResponse(
        request,
        "kb_list.html",
        {
            "kbs": [kb.model_dump() for kb in service.list_kbs()],
            "maintainer_configured": bool(maintainer_token()),
            "error_message": _maintainer_error_message(error),
        },
    )


@router.post("")
@router.post("/")
async def kb_create_page(
    kb_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    try:
        _assert_ui_maintainer(maintainer_token_value)
        get_knowledge_service().create_kb(kb_id, name, description, actor="portal")
    except KnowledgeError:
        return _write_error_redirect("/portal/kb")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.get("/{kb_id}", response_class=HTMLResponse)
def kb_detail_page(
    request: Request,
    kb_id: str,
    error: str = "",
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    kb = service.get_kb(kb_id).model_dump()
    collections = [item.model_dump() for item in service.list_collections(kb_id)]
    documents = [item.model_dump() for item in service.list_documents(kb_id)]
    health = service.kb_health(kb_id)

    return templates.TemplateResponse(
        request,
        "kb_detail.html",
        {
            "kb": kb,
            "collections": collections,
            "documents": documents,
            "health": health,
            "search_results": [],
            "query": "",
            "maintainer_configured": bool(maintainer_token()),
            "error_message": _maintainer_error_message(error),
        },
    )


@router.post("/{kb_id}/collections")
async def kb_create_collection(
    kb_id: str,
    collection_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    priority: int = Form(100),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.create_collection(kb_id, collection_id, name, description, priority, actor="portal")
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/collections/{collection_id}")
async def kb_update_collection(
    kb_id: str,
    collection_id: str,
    name: str = Form(""),
    description: str = Form(""),
    priority: int = Form(100),
    archived: bool = Form(False),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.update_collection(
            kb_id,
            collection_id,
            {
                "name": name,
                "description": description,
                "priority": priority,
                "archived": archived,
            },
            actor="portal",
        )
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/documents/upload")
async def kb_upload_document(
    kb_id: str,
    collection_id: str = Form(...),
    document_id: str = Form(...),
    title: str = Form(...),
    source_type: str = Form("portal"),
    external_id: str = Form(""),
    confidence: float = Form(1.0),
    effective_from: str = Form(""),
    effective_to: str = Form(""),
    maintainer_token_value: str = Form(""),
    file: UploadFile = File(...),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    raw = await file.read()
    extension = ".txt"
    if file.filename and "." in file.filename:
        extension = "." + file.filename.split(".")[-1].lower()

    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.upload_document(
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
            extension=extension,
            actor="portal",
        )
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/documents/{document_id}/publish")
async def kb_publish_document(
    kb_id: str,
    document_id: str,
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.publish_document(kb_id, document_id, actor="portal")
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/documents/{document_id}/archive")
async def kb_archive_document(
    kb_id: str,
    document_id: str,
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.archive_document(kb_id, document_id, actor="portal")
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/documents/{document_id}/supersede")
async def kb_supersede_document(
    kb_id: str,
    document_id: str,
    replacement_document_id: str = Form(...),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.supersede_document(kb_id, document_id, replacement_document_id, actor="portal")
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.post("/{kb_id}/reindex")
async def kb_reindex(
    kb_id: str,
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    try:
        _assert_ui_maintainer(maintainer_token_value)
        service.reindex(kb_id, actor="portal")
    except KnowledgeError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.get("/{kb_id}/search", response_class=HTMLResponse)
def kb_search_page(
    request: Request,
    kb_id: str,
    q: str = "",
    collection_id: str = "",
    top_k: int = 10,
    _: None = Depends(require_kb_enabled),
):
    service = get_knowledge_service()
    results = []

    if q.strip():
        response = service.search(
            kb_id,
            SearchRequest(
                query=q,
                collection_id=collection_id or None,
                top_k=top_k,
            ),
        )
        results = [item.model_dump() for item in response.results]

    return templates.TemplateResponse(
        request,
        "kb_search.html",
        {
            "kb": service.get_kb(kb_id).model_dump(),
            "collections": [item.model_dump() for item in service.list_collections(kb_id)],
            "search_results": results,
            "query": q,
            "selected_collection_id": collection_id,
            "top_k": top_k,
        },
    )
