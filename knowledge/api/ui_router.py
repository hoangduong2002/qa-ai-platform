from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from knowledge.api.deps import require_kb_enabled
from knowledge.domain.models import SearchRequest
from knowledge.domain.errors import (
    KnowledgeConflictError,
    KnowledgeError,
    KnowledgeNotFoundError,
    KnowledgePackageError,
    KnowledgePackageSecurityError,
    KnowledgePermissionError,
    KnowledgeValidationError,
)
from knowledge.services.config import knowledge_base_enabled, maintainer_token
from knowledge.services.package_importer import KnowledgePackageImporter
from knowledge.services.runtime import get_knowledge_service


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["knowledge_base_enabled"] = knowledge_base_enabled

router = APIRouter(prefix="/portal/kb", tags=["Knowledge Base UI"])
logger = logging.getLogger(__name__)


def _assert_ui_maintainer(provided_token: str) -> None:
    expected = maintainer_token()
    if not expected or provided_token != expected:
        raise KnowledgePermissionError("Maintainer token is invalid for write operation.")


def _maintainer_error_message(error_code: str) -> str:
    if error_code == "maintainer_access_required":
        return "Maintainer access is required for this write operation. Check the configured token and try again."
    return ""


def _write_error_redirect(path: str) -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    query = urlencode({"error": "maintainer_access_required"})
    return RedirectResponse(url=f"{path}{separator}{query}", status_code=303)


def _render_kb_detail(
    request: Request,
    kb_id: str,
    *,
    error_message: str = "",
    package_result: dict | None = None,
    status_code: int = 200,
):
    service = get_knowledge_service()
    return templates.TemplateResponse(
        request,
        "kb_detail.html",
        {
            "kb": service.get_kb(kb_id).model_dump(),
            "collections": [item.model_dump() for item in service.list_collections(kb_id)],
            "documents": [item.model_dump() for item in service.list_documents(kb_id)],
            "health": service.kb_health(kb_id),
            "search_results": [],
            "query": "",
            "maintainer_configured": bool(maintainer_token()),
            "error_message": error_message,
            "package_result": package_result,
        },
        status_code=status_code,
    )


def _render_kb_list(
    request: Request,
    *,
    error_message: str = "",
    status_code: int = 200,
):
    service = get_knowledge_service()
    return templates.TemplateResponse(
        request,
        "kb_list.html",
        {
            "kbs": [kb.model_dump() for kb in service.list_kbs()],
            "maintainer_configured": bool(maintainer_token()),
            "error_message": error_message,
        },
        status_code=status_code,
    )


async def _inspect_portal_package(
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
    raise KnowledgePackageError("Select a ZIP package or folder files.")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def kb_list_page(
    request: Request,
    error: str = "",
    _: None = Depends(require_kb_enabled),
):
    return _render_kb_list(
        request,
        error_message=_maintainer_error_message(error),
    )


@router.post("")
@router.post("/")
async def kb_create_page(
    request: Request,
    kb_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    jira_project_keys: str = Form(""),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    try:
        _assert_ui_maintainer(maintainer_token_value)
        values = [] if not jira_project_keys.strip() else jira_project_keys.split(",")
        get_knowledge_service().create_kb(
            kb_id,
            name,
            description,
            actor="portal",
            jira_project_keys=values,
        )
    except KnowledgePermissionError:
        return _write_error_redirect("/portal/kb")
    except KnowledgeConflictError as error:
        return _render_kb_list(request, error_message=str(error), status_code=409)
    except KnowledgeValidationError as error:
        return _render_kb_list(request, error_message=str(error), status_code=400)
    except KnowledgeNotFoundError as error:
        return _render_kb_list(request, error_message=str(error), status_code=404)
    except Exception:
        logger.exception("Unexpected Knowledge Base creation failure for kb_id=%s", kb_id)
        return _render_kb_list(
            request,
            error_message="Unable to create the Knowledge Base.",
            status_code=500,
        )
    return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)


@router.get("/{kb_id}", response_class=HTMLResponse)
def kb_detail_page(
    request: Request,
    kb_id: str,
    error: str = "",
    _: None = Depends(require_kb_enabled),
):
    return _render_kb_detail(
        request,
        kb_id,
        error_message=_maintainer_error_message(error),
    )


@router.post("/{kb_id}/jira-project-keys", response_class=HTMLResponse)
async def kb_update_jira_project_keys(
    request: Request,
    kb_id: str,
    jira_project_keys: str = Form(""),
    maintainer_token_value: str = Form(""),
    _: None = Depends(require_kb_enabled),
):
    try:
        _assert_ui_maintainer(maintainer_token_value)
        values = [] if not jira_project_keys.strip() else jira_project_keys.split(",")
        get_knowledge_service().update_kb(
            kb_id,
            {"jira_project_keys": values},
            actor="portal",
        )
        return RedirectResponse(url=f"/portal/kb/{kb_id}", status_code=303)
    except KnowledgePermissionError:
        return _write_error_redirect(f"/portal/kb/{kb_id}")
    except KnowledgeConflictError as error:
        return _render_kb_detail(request, kb_id, error_message=str(error), status_code=409)
    except KnowledgeValidationError as error:
        return _render_kb_detail(request, kb_id, error_message=str(error), status_code=400)
    except KnowledgeNotFoundError as error:
        return _render_kb_list(request, error_message=str(error), status_code=404)
    except Exception:
        logger.exception("Unexpected Jira project-key update failure for kb_id=%s", kb_id)
        return _render_kb_detail(
            request,
            kb_id,
            error_message="Unable to update Jira Project Keys.",
            status_code=500,
        )


@router.post("/{kb_id}/packages/inspect", response_class=HTMLResponse)
async def kb_inspect_package(
    request: Request,
    kb_id: str,
    conflict_mode: str = Form("skip"),
    maintainer_token_value: str = Form(""),
    zip_file: UploadFile | None = File(None),
    folder_files: list[UploadFile] = File(default=[]),
    _: None = Depends(require_kb_enabled),
):
    try:
        _assert_ui_maintainer(maintainer_token_value)
        plan = await _inspect_portal_package(
            kb_id=kb_id,
            conflict_mode=conflict_mode,
            zip_file=zip_file,
            folder_files=folder_files,
        )
        return _render_kb_detail(request, kb_id, package_result={"status": "inspection", "plan": plan.to_dict()})
    except KnowledgePermissionError:
        return _render_kb_detail(request, kb_id, error_message="Maintainer authorization failed.", status_code=403)
    except KnowledgePackageSecurityError as error:
        return _render_kb_detail(request, kb_id, error_message=f"Archive security violation: {error}", status_code=400)
    except KnowledgePackageError as error:
        return _render_kb_detail(request, kb_id, error_message=f"Package validation failed: {error}", status_code=400)
    except Exception:
        logger.exception("Unexpected Knowledge Package inspection failure for kb_id=%s", kb_id)
        return _render_kb_detail(request, kb_id, error_message="Unexpected package inspection error.", status_code=500)


@router.post("/{kb_id}/packages/import", response_class=HTMLResponse)
async def kb_import_package(
    request: Request,
    kb_id: str,
    conflict_mode: str = Form("skip"),
    auto_publish: bool = Form(False),
    dry_run: bool = Form(False),
    maintainer_token_value: str = Form(""),
    zip_file: UploadFile | None = File(None),
    folder_files: list[UploadFile] = File(default=[]),
    _: None = Depends(require_kb_enabled),
):
    try:
        _assert_ui_maintainer(maintainer_token_value)
        plan = await _inspect_portal_package(
            kb_id=kb_id,
            conflict_mode=conflict_mode,
            zip_file=zip_file,
            folder_files=folder_files,
        )
        if dry_run:
            result = {"status": "dry_run", "plan": plan.to_dict()}
        elif not plan.can_execute:
            return _render_kb_detail(
                request,
                kb_id,
                error_message="Package import is blocked by validation errors or conflicts.",
                package_result={"status": "blocked", "plan": plan.to_dict()},
                status_code=409,
            )
        else:
            result = KnowledgePackageImporter(get_knowledge_service()).execute_import(
                plan,
                auto_publish=auto_publish,
                actor="portal",
            )
        return _render_kb_detail(request, kb_id, package_result=result)
    except KnowledgePermissionError:
        return _render_kb_detail(request, kb_id, error_message="Maintainer authorization failed.", status_code=403)
    except KnowledgePackageSecurityError as error:
        return _render_kb_detail(request, kb_id, error_message=f"Archive security violation: {error}", status_code=400)
    except KnowledgePackageError as error:
        return _render_kb_detail(request, kb_id, error_message=f"Package validation failed: {error}", status_code=400)
    except Exception:
        logger.exception("Unexpected Knowledge Package import failure for kb_id=%s", kb_id)
        return _render_kb_detail(request, kb_id, error_message="Unexpected package import error.", status_code=500)


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
