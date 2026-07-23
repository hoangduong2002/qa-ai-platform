from pathlib import Path
from typing import Any
from urllib.parse import urlencode
import asyncio
import json
import logging
import threading

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.requirement_workflow_service import (
    create_jira_requirement_and_run_analysis,
    run_incremental_requirement_questions,
    run_incremental_scenarios,
    run_incremental_testcases,
    run_requirement_questions,
    run_requirement_summary,
)
from app.services.web_design_artifact_service import (
    approve_structure_version,
    export_structure_version_to_excel,
    generate_structure_for_web,
    get_structure_review,
    get_structure_review_json,
    get_structure_session_for_web,
    get_structure_version_json,
    improve_structure_from_ai_review,
    improve_structure_from_comment,
    list_structure_versions,
    save_structure_json_as_new_version,
    self_review_structure_version,
)
from app.services.web_requirement_service import (
    create_manual_requirement,
    delete_requirement,
    export_requirement_analysis_to_excel,
    export_requirement_summary_to_excel,
    get_clarification_questions,
    get_requirement_detail,
    list_requirements,
    sanitize_existing_requirement,
    save_clarification_answers,
    update_requirement,
    normalize_requirement_id,
    requirement_exists,
)
from app.services.web_test_design_artifact_service import (
    approve_scenarios,
    approve_testcases,
    export_testcases_excel,
    get_coverage_review,
    get_coverage_review_json,
    get_final_review,
    get_final_review_json,
    get_incremental_testcases,
    get_scenarios_json,
    get_testcases,
    get_testcases_json,
    improve_scenarios_from_ai_review,
    improve_scenarios_from_human_review,
    improve_testcases_from_ai_review,
    improve_testcases_from_human_review,
    list_scenario_versions,
    list_testcase_versions,
    load_scenario_session,
    load_testcase_session,
    run_final_review,
    run_scenario_coverage_review,
    save_testcases_json_as_new_version,
    export_scenarios_excel,
    export_incremental_testcases_excel,
)
from app.services.test_design_workflow_service import (
    generate_scope_and_scenarios,
    generate_testcases_from_approved_scenarios,
)
from app.services.report_service import generate_system_report
from app.services.web_report_preview_service import build_report_preview
from app.services.llm_router_service import test_all_llm_providers
from app.services.knowledge_system_service import load_knowledge_system
from knowledge.services.config import knowledge_base_enabled
from app.services.knowledge_reference_review.service import (
    create_review_request,
    load_review_dashboard,
    review_reference_decision,
)
from app.services.knowledge_reference_review.models import RequestedDecision
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
    get_default_ai_mode,
    portal_ai_mode_dependency,
)
from app.services.ai_provider_error_service import format_provider_error
from app.services.chat_file_extractor_service import save_and_extract_uploads
from app.services.chat_service import (
    create_chat_session,
    get_chat_sessions_dir,
    is_unlock_token_valid,
    list_chat_sessions,
    load_chat_messages,
    load_chat_session,
    send_chat_message,
    soft_delete_chat_session,
    unlock_chat_session,
    public_chat_session,
)
from app.services.portal_job_service import (
    PortalConcurrencyError,
    PortalJobBusyError,
    check_provider_safety,
    create_job,
    get_job_status,
    run_portal_ticket_job,
)
from app.services.jira_delta_service import (
    build_and_save_latest_stored_jira_snapshot,
    sync_jira_changes_for_requirement,
)
from app.services.jira_requirement_service import (
    figma_enabled_by_default,
    jira_subtasks_enabled_by_default,
    parse_jira_ticket_ids,
)
from app.services.requirement_source_service import (
    has_jira_snapshot as requirement_has_jira_snapshot,
    is_jira_requirement as requirement_is_jira,
)
from app.services.impact_mapping_service import (
    SAFETY_FULL_RECOMMENDED,
    SAFETY_MANUAL_REVIEW,
    build_and_save_regeneration_plan,
    load_latest_regeneration_plan,
)
from app.services.traceability_gate.config import authorized_qa_leads
from app.services.traceability_gate.export_guard import (
    create_export_override,
    evaluate_export,
)
from app.services.quality_feedback.models import FeedbackAction, FeedbackReason
from app.services.quality_feedback.service import (
    authorized_feedback_reviewers,
    record_testcase_feedback,
    ticket_quality_dashboard,
)
from fastapi.responses import JSONResponse


BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(prefix="/portal", tags=["Web Portal"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

templates.env.globals["portal_default_ai_mode"] = get_default_ai_mode()
templates.env.globals["knowledge_base_enabled"] = knowledge_base_enabled

JIRA_SYNC_NOT_AVAILABLE = (
    "This requirement was not imported from Jira. Jira sync is not available."
)

logger = logging.getLogger(__name__)


def _redirect_detail(ticket_id: str, tab: str = "analysis", **params):
    anchor = params.pop("anchor", None)
    query_params = {"tab": tab}
    for key, value in params.items():
        if value is not None:
            query_params[key] = value
    fragment = f"#{anchor}" if anchor else ""

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}?{urlencode(query_params)}{fragment}",
        status_code=303,
    )


@router.get("/reports", response_class=HTMLResponse)
async def report_preview(request: Request):
    return templates.TemplateResponse(
        request,
        "report_preview.html",
        build_report_preview(),
    )


@router.get("/reports/download")
async def download_system_report():
    report_file = generate_system_report()
    report_path = Path(report_file)

    return FileResponse(
        path=str(report_path),
        filename=report_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "sessions": list_chat_sessions(),
            "portal_default_ai_mode": get_default_ai_mode(),
        },
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_system_page(request: Request):
    context = load_knowledge_system()
    context["portal_default_ai_mode"] = get_default_ai_mode()

    return templates.TemplateResponse(
        request,
        "knowledge_system.html",
        context,
    )


@router.get("/chat/sessions")
async def chat_sessions():
    return JSONResponse({"sessions": list_chat_sessions()})


@router.post("/chat/sessions")
async def create_portal_chat_session(
    ai_mode: str = Form(""),
    title: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
):
    try:
        session = create_chat_session(
            ai_mode=ai_mode or get_default_ai_mode(),
            title=title,
            password=password,
            confirm_password=confirm_password,
        )
    except ValueError as error:
        return JSONResponse(
            {
                "ok": False,
                "error": str(error),
            },
            status_code=400,
        )
    return JSONResponse(session)


@router.get("/chat/sessions/{session_id}")
async def get_portal_chat_session(
    session_id: str,
    x_chat_unlock_token: str = Header(default=""),
):
    try:
        session = load_chat_session(session_id)
        if session.get("deleted"):
            raise FileNotFoundError("Chat session not found.")
        public_session = public_chat_session(session)
        if session.get("password_protected") and not is_unlock_token_valid(
            session_id,
            x_chat_unlock_token,
        ):
            return JSONResponse(
                {
                    "session": public_session,
                    "messages": [],
                    "password_required": True,
                }
            )
        messages = load_chat_messages(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Chat session not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return JSONResponse(
        {
            "session": public_session,
            "messages": messages,
            "password_required": False,
        }
    )


@router.post("/chat/sessions/{session_id}/unlock")
async def unlock_portal_chat_session(
    session_id: str,
    payload: dict[str, Any] = Body(default={}),
):
    try:
        result = unlock_chat_session(session_id, str(payload.get("password") or ""))
    except PermissionError as error:
        return JSONResponse(
            {
                "ok": False,
                "error": str(error),
            },
            status_code=403,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Chat session not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return JSONResponse(result)


@router.delete("/chat/sessions/{session_id}")
async def delete_portal_chat_session(session_id: str):
    try:
        soft_delete_chat_session(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Chat session not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return JSONResponse(
        {
            "ok": True,
            "message": "Chat deleted.",
        }
    )


@router.post("/chat/sessions/{session_id}/messages")
async def post_portal_chat_message(
    session_id: str,
    ai_mode: str = Form(""),
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    x_chat_unlock_token: str = Header(default=""),
):
    try:
        session = load_chat_session(session_id)
        if session.get("deleted"):
            raise FileNotFoundError("Chat session not found.")
        if session.get("password_protected") and not is_unlock_token_valid(
            session_id,
            x_chat_unlock_token,
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Unlock this chat before sending a message.",
                    "password_required": True,
                    "warnings": [],
                },
                status_code=403,
            )
        session_dir = get_chat_sessions_dir() / session_id
        attachments, extracted_context, warnings = await save_and_extract_uploads(
            session_dir=session_dir,
            files=files,
        )
        result = send_chat_message(
            session_id=session_id,
            user_message=message,
            ai_mode=ai_mode or session.get("ai_mode") or get_default_ai_mode(),
            attachments=attachments,
            extracted_context=extracted_context,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Chat session not found.") from error
    except ValueError as error:
        return JSONResponse(
            {
                "ok": False,
                "error": str(error),
                "warnings": [],
            },
            status_code=400,
        )

    result["warnings"] = warnings
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "requirements": list_requirements(),
            "portal_default_ai_mode": get_default_ai_mode(),
            "jira_load_subtasks_default": jira_subtasks_enabled_by_default(),
            "jira_load_figma_default": figma_enabled_by_default(),
        },
    )


@router.get("/requirements/new", response_class=HTMLResponse)
async def new_requirement_form(request: Request):
    return templates.TemplateResponse(request, "requirement_form.html", {})


@router.post("/requirements")
async def create_requirement(
    requirement_name: str = Form(...),
    description: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    ticket_id = await create_manual_requirement(
        requirement_name=requirement_name,
        description=description,
        files=files,
    )
    return RedirectResponse(url=f"/portal/requirements/{ticket_id}", status_code=303)


@router.post("/requirements/from-jira")
async def create_requirement_from_jira(
    _: None = Depends(portal_ai_mode_dependency),
    issue_key: str = Form(...),
    jira_pat: str = Form(""),
    refresh_existing: str = Form("false"),
    load_subtasks: bool | None = Form(None),
    load_figma: bool | None = Form(None),
):
    try:
        main_ticket_id, _ = parse_jira_ticket_ids(issue_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    ticket_id = normalize_requirement_id(main_ticket_id)
    load_subtasks = (
        jira_subtasks_enabled_by_default()
        if load_subtasks is None
        else load_subtasks
    )
    load_figma = (
        figma_enabled_by_default()
        if load_figma is None
        else load_figma
    )
    job_id = create_job(
        ticket_id=ticket_id,
        action="create_requirement_from_jira",
        ai_mode_context=get_current_portal_ai_mode(),
    )

    _dispatch_portal_job(
        ticket_id=ticket_id,
        action="create_requirement_from_jira",
        ai_mode_context=get_current_portal_ai_mode(),
        job_callable=lambda: create_jira_requirement_and_run_analysis(
            issue_key=issue_key,
            jira_pat=jira_pat,
            refresh_existing=refresh_existing.lower() == "true",
            load_subtasks=load_subtasks,
            load_figma=load_figma,
            ai_mode=(get_current_portal_ai_mode() or {}).get("ai_mode"),
            source_channel="web",
        ),
        job_id=job_id,
    )

    return JSONResponse(
        {
            "job_id": job_id,
            "ticket_id": ticket_id,
            "detail_url": f"/portal/requirements/{ticket_id}",
        },
        status_code=202,
    )


@router.get("/jobs/{job_id}/status")
async def portal_job_status(job_id: str):
    job_status = get_job_status(job_id)

    if not job_status:
        raise HTTPException(status_code=404, detail="Job not found.")

    ticket_id = job_status.get("ticket_id") or ""
    job_status["detail_url"] = f"/portal/requirements/{ticket_id}" if ticket_id else None

    return JSONResponse(job_status)


@router.get("/requirements/check-jira")
async def check_jira_requirement(issue_key: str):
    try:
        main_ticket_id, _ = parse_jira_ticket_ids(issue_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    ticket_id = normalize_requirement_id(main_ticket_id)

    return JSONResponse(
        {
            "ticket_id": ticket_id,
            "exists": requirement_exists(ticket_id),
            "detail_url": f"/portal/requirements/{ticket_id}",
        }
    )


@router.post("/llm/test-all")
async def test_all_llms():
    return JSONResponse(test_all_llm_providers())


@router.get("/requirements/{ticket_id}", response_class=HTMLResponse)
async def requirement_detail(
    request: Request,
    ticket_id: str,
    tab: str | None = None,
    structure_version: str = "latest",
    scenario_version: str = "latest",
    testcase_version: str = "latest",
    testcase_execution_type: str = "",
    error: str = "",
    success: str = "",
):
    detail = get_requirement_detail(ticket_id)
    is_jira_source = requirement_is_jira(ticket_id)
    has_jira_snapshot = requirement_has_jira_snapshot(ticket_id)
    can_sync_jira = is_jira_source and has_jira_snapshot

    structure_session = get_structure_session_for_web(ticket_id)
    scenario_session = load_scenario_session(ticket_id)
    testcase_session = load_testcase_session(ticket_id)

    if tab in ["clarifications", "changes", "incremental"]:
        tab = "analysis"
    elif tab not in ["analysis", "design"]:
        tab = (
            "design"
            if structure_session.get("current_version")
            or scenario_session.get("current_version")
            or testcase_session.get("current_version")
            else "analysis"
        )

    selected_structure_json = get_structure_version_json(ticket_id, structure_version)
    selected_structure_review = get_structure_review(ticket_id, structure_version)
    selected_scenarios_json = get_scenarios_json(ticket_id, scenario_version)
    selected_coverage_review = get_coverage_review(ticket_id, scenario_version)
    selected_testcases = get_testcases(ticket_id, testcase_version)
    selected_testcases_json = get_testcases_json(ticket_id, testcase_version)
    selected_testcase_filter = str(testcase_execution_type or "").upper()

    if selected_testcase_filter in {"AUTOMATION", "MANUAL", "HYBRID"}:
        filtered_testcases = [
            testcase
            for testcase in selected_testcases
            if testcase.get("execution_type") == selected_testcase_filter
        ]
        selected_testcases_json = json.dumps(
            filtered_testcases,
            indent=2,
            ensure_ascii=False,
        ) if filtered_testcases else ""
    else:
        selected_testcase_filter = ""

    testcase_execution_counts = {
        "AUTOMATION": sum(
            1
            for testcase in selected_testcases
            if testcase.get("execution_type") == "AUTOMATION"
        ),
        "MANUAL": sum(
            1
            for testcase in selected_testcases
            if testcase.get("execution_type") == "MANUAL"
        ),
        "HYBRID": sum(
            1
            for testcase in selected_testcases
            if testcase.get("execution_type") == "HYBRID"
        ),
    }
    selected_final_review = get_final_review(ticket_id, testcase_version)
    incremental_testcases = get_incremental_testcases(ticket_id)
    try:
        export_gate_status = evaluate_export(
            ticket_id=ticket_id,
            testcases=selected_testcases,
            testcase_version=testcase_version,
            export_format="function_based_xlsx",
        ).model_dump(mode="json")
    except Exception as gate_error:
        logger.exception("Failed to evaluate export gate. ticket_id=%s", ticket_id)
        export_gate_status = {
            "status": "UNAVAILABLE",
            "gate_enabled": True,
            "blockers": [],
            "warnings": [],
            "uncovered_requirements": [],
            "unsupported_results": [],
            "conflicts": [],
            "approval_status": {},
            "error": str(gate_error),
        }
    incremental_export_gate_status = None
    if incremental_testcases:
        try:
            incremental_export_gate_status = evaluate_export(
                ticket_id=ticket_id,
                testcases=incremental_testcases,
                testcase_version="incremental-latest",
                export_format="incremental_xlsx",
            ).model_dump(mode="json")
        except Exception as gate_error:
            incremental_export_gate_status = {
                "status": "UNAVAILABLE",
                "blockers": [],
                "warnings": [],
                "error": str(gate_error),
            }

    detail.update(
        {
            "tab": tab,
            "structure_version": structure_version,
            "scenario_version": scenario_version,
            "testcase_version": testcase_version,
            "testcase_execution_type": selected_testcase_filter,
            "testcase_execution_counts": testcase_execution_counts,
            "structure_versions": list_structure_versions(ticket_id),
            "scenario_versions": list_scenario_versions(ticket_id),
            "testcase_versions": list_testcase_versions(ticket_id),
            "structure_session": structure_session,
            "scenario_session": scenario_session,
            "testcase_session": testcase_session,
            "selected_structure_json": selected_structure_json,
            "selected_structure_review": selected_structure_review,
            "selected_structure_review_json": get_structure_review_json(
                ticket_id,
                structure_version,
            ),
            "selected_scenarios_json": selected_scenarios_json,
            "selected_coverage_review": selected_coverage_review,
            "selected_coverage_review_json": get_coverage_review_json(
                ticket_id,
                scenario_version,
            ),
            "selected_testcases_json": selected_testcases_json,
            "selected_testcases": selected_testcases,
            "quality_feedback_dashboard": ticket_quality_dashboard(ticket_id),
            "quality_feedback_available": bool(authorized_feedback_reviewers()),
            "quality_feedback_actions": [item.value for item in FeedbackAction],
            "quality_feedback_reasons": [item.value for item in FeedbackReason],
            "selected_final_review": selected_final_review,
            "export_gate_status": export_gate_status,
            "export_override_available": bool(authorized_qa_leads()),
            "incremental_export_gate_status": incremental_export_gate_status,
            "selected_final_review_json": get_final_review_json(
                ticket_id,
                testcase_version,
            ),
            "has_testcase_structure": bool(selected_structure_json),
            "has_approved_structure": bool(structure_session.get("approved")),
            "has_scenarios": bool(selected_scenarios_json),
            "has_approved_scenarios": bool(scenario_session.get("approved")),
            "has_testcases": bool(selected_testcases),
            "has_approved_testcases": bool(testcase_session.get("approved")),
            "is_jira_requirement": is_jira_source,
            "has_jira_snapshot": has_jira_snapshot,
            "can_sync_jira": can_sync_jira,
            "error": error,
            "success": success,
        }
    )

    return templates.TemplateResponse(request, "requirement_detail.html", detail)


@router.get("/requirements/{ticket_id}/edit", response_class=HTMLResponse)
async def edit_requirement_form(request: Request, ticket_id: str):
    return templates.TemplateResponse(
        request,
        "requirement_edit.html",
        get_requirement_detail(ticket_id),
    )


@router.post("/requirements/{ticket_id}/edit")
async def edit_requirement(
    ticket_id: str,
    summary: str = Form(...),
    description: str = Form(""),
    comments: str = Form(""),
):
    update_requirement(
        ticket_id=ticket_id,
        summary=summary,
        description=description,
        comments=comments,
    )
    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/delete")
async def remove_requirement(ticket_id: str):
    delete_requirement(ticket_id)
    return RedirectResponse(url="/portal", status_code=303)


@router.post("/requirements/{ticket_id}/sanitize")
async def sanitize_requirement(ticket_id: str):
    sanitize_existing_requirement(ticket_id)
    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/snapshot-jira")
async def snapshot_jira_requirement(ticket_id: str):
    try:
        _ensure_jira_requirement(ticket_id)
        result = build_and_save_latest_stored_jira_snapshot(ticket_id)
    except ValueError as error:
        status_code = 400 if str(error) == JIRA_SYNC_NOT_AVAILABLE else 404
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    return JSONResponse(result)


@router.post("/requirements/{ticket_id}/sync-jira")
async def sync_jira_requirement(
    ticket_id: str,
    jira_pat: str = Form(""),
):
    try:
        _ensure_jira_requirement(ticket_id)
        result = sync_jira_changes_for_requirement(
            ticket_id=ticket_id,
            jira_pat=jira_pat,
            source_channel="web",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return JSONResponse(result)


@router.post("/requirements/{ticket_id}/build-regeneration-plan")
async def build_regeneration_plan_for_requirement(ticket_id: str):
    try:
        _ensure_jira_requirement(ticket_id)
        result = build_and_save_regeneration_plan(ticket_id)
    except ValueError as error:
        message = str(error)
        logger.warning(
            "Build regeneration plan validation failed. ticket_id=%s error=%s",
            ticket_id,
            message,
        )
        return JSONResponse(
            {
                "status": "failed",
                "message": message,
                "detail": message,
                "result": {},
            },
            status_code=400,
        )
    except Exception as error:
        message = (
            "Build regeneration plan failed. Please check prerequisite artifacts "
            "and try again."
        )
        logger.exception(
            "Build regeneration plan failed unexpectedly. ticket_id=%s",
            ticket_id,
        )
        return JSONResponse(
            {
                "status": "failed",
                "message": message,
                "detail": message,
                "result": {},
            },
            status_code=500,
        )

    return JSONResponse(
        {
            "status": "completed",
            "message": "Regeneration plan built.",
            "result": result,
        }
    )


@router.post("/requirements/{ticket_id}/analyze")
async def analyze_requirement(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="analyze_requirement",
        job_callable=lambda: run_requirement_questions(
            ticket_id=ticket_id,
            ai_mode=ai_mode,
        ),
    )

    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/analyze-incremental")
async def analyze_incremental_requirement(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    try:
        _ensure_jira_requirement(ticket_id)
        # Safety gate before dispatching
        _check_incremental_safety(ticket_id)
        await _run_ticket_job(
            ticket_id=ticket_id,
            action="analyze_incremental_requirement",
            job_callable=lambda: run_incremental_requirement_questions(
                ticket_id=ticket_id,
                ai_mode=ai_mode,
                source_channel="web",
            ),
        )
    except (RuntimeError, ValueError, HTTPException) as error:
        detail = str(error.detail) if isinstance(error, HTTPException) else str(error)
        return _redirect_detail(ticket_id, error=detail)

    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/scenarios/generate-incremental")
async def generate_incremental_scenarios_for_web(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    try:
        _ensure_jira_requirement(ticket_id)
        # Safety gate before dispatching
        _check_incremental_safety(ticket_id)
        await _run_ticket_job(
            ticket_id=ticket_id,
            action="generate_incremental_scenarios",
            job_callable=lambda: run_incremental_scenarios(
                ticket_id=ticket_id,
                ai_mode=ai_mode,
                source_channel="web",
            ),
        )
    except (RuntimeError, ValueError, HTTPException) as error:
        detail = str(error.detail) if isinstance(error, HTTPException) else str(error)
        return _redirect_detail(ticket_id, tab="design", error=detail)

    return _redirect_detail(ticket_id, tab="design")


@router.post("/requirements/{ticket_id}/testcases/generate-incremental")
async def generate_incremental_testcases_for_web(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    try:
        _ensure_jira_requirement(ticket_id)
        # Safety gate before dispatching
        _check_incremental_safety(ticket_id)
        await _run_ticket_job(
            ticket_id=ticket_id,
            action="generate_incremental_testcases",
            job_callable=lambda: run_incremental_testcases(
                ticket_id=ticket_id,
                ai_mode=ai_mode,
                source_channel="web",
            ),
        )
    except (RuntimeError, ValueError, HTTPException) as error:
        detail = str(error.detail) if isinstance(error, HTTPException) else str(error)
        return _redirect_detail(ticket_id, tab="design", error=detail)

    return _redirect_detail(ticket_id, tab="design")


@router.get("/requirements")
async def requirements_index():
    return RedirectResponse(
        url="/portal",
        status_code=303,
    )


@router.post("/requirements/{ticket_id}/summary")
async def generate_summary(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="generate_requirement_summary",
        job_callable=lambda: run_requirement_summary(
            ticket_id=ticket_id,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id)


@router.get("/requirements/{ticket_id}/knowledge-review", response_class=HTMLResponse)
async def knowledge_reference_review_page(request: Request, ticket_id: str, error: str = "", success: str = ""):
    detail = get_requirement_detail(ticket_id)
    dashboard = load_review_dashboard(ticket_id)
    detail.update(
        {
            "error": error,
            "success": success,
            "review_dashboard": dashboard,
        }
    )
    return templates.TemplateResponse(request, "knowledge_reference_review.html", detail)


@router.get("/requirements/{ticket_id}/knowledge-references")
async def requirement_knowledge_references(ticket_id: str):
    detail = get_requirement_detail(ticket_id)
    dashboard = load_review_dashboard(ticket_id)
    return JSONResponse(
        {
            "ticket_id": ticket_id,
            "knowledge": detail.get("knowledge_snapshot"),
            "review": {
                "review_required": dashboard.get("review_required", False),
                "review_count": dashboard.get("review_count", 0),
                "candidates": dashboard.get("candidates", []),
            },
        }
    )


@router.post("/requirements/{ticket_id}/knowledge-review/search")
async def search_knowledge_reference_candidates(
    ticket_id: str,
    reviewer_id: str = Form(""),
    kb_id: str = Form(...),
    query: str = Form(...),
    retrieval_need: str = Form(""),
    jira_issue_being_clarified: str = Form(""),
):
    try:
        create_review_request(
            ticket_id=ticket_id,
            kb_id=kb_id,
            query=query,
            retrieval_need=retrieval_need or "General requirement clarification",
            jira_issue_being_clarified=jira_issue_being_clarified or "General Jira statement",
            reviewer_id=reviewer_id,
            top_k=10,
        )
    except PermissionError as error:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error={str(error)}",
            status_code=303,
        )
    except Exception as error:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error={str(error)}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}/knowledge-review?success=Candidate references retrieved.",
        status_code=303,
    )


@router.post("/requirements/{ticket_id}/knowledge-review/decision")
async def review_knowledge_reference_decision(
    ticket_id: str,
    source_result_id: str = Form(...),
    requested_decision: str = Form(...),
    decision_reason: str = Form(""),
    review_note: str = Form(""),
    reviewed_by: str = Form(""),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")

    try:
        decision = RequestedDecision(requested_decision)
    except Exception:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error=Invalid review decision.",
            status_code=303,
        )

    try:
        review_reference_decision(
            ticket_id=ticket_id,
            source_result_id=source_result_id,
            requested_decision=decision,
            decision_reason=decision_reason or "Reviewer decision",
            review_note=review_note,
            reviewed_by=reviewed_by,
            ai_mode=ai_mode,
        )
    except PermissionError as error:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error={str(error)}",
            status_code=303,
        )
    except Exception as error:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error={str(error)}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}/knowledge-review?success=Reference review decision saved.",
        status_code=303,
    )


@router.post("/requirements/{ticket_id}/knowledge-review/rerun")
async def rerun_analysis_with_reviewed_knowledge(
    ticket_id: str,
    reviewed_by: str = Form(""),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    try:
        await _run_ticket_job(
            ticket_id=ticket_id,
            action="rerun_analysis_with_reviewed_knowledge",
            job_callable=lambda: run_requirement_questions(
                ticket_id=ticket_id,
                ai_mode=ai_mode,
                source_channel="web",
                use_reviewed_references=True,
                adjusted_by=reviewed_by or "reviewer",
            ),
        )
    except Exception as error:
        return RedirectResponse(
            url=f"/portal/requirements/{ticket_id}/knowledge-review?error={str(error)}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}/knowledge-review?success=Analysis re-run with reviewed references.",
        status_code=303,
    )


@router.get("/requirements/{ticket_id}/analysis/excel")
async def download_requirement_analysis_excel(ticket_id: str):
    excel_file = export_requirement_analysis_to_excel(ticket_id=ticket_id)
    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/requirements/{ticket_id}/summary/excel")
async def download_requirement_summary_excel(ticket_id: str):
    excel_file = export_requirement_summary_to_excel(ticket_id)
    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/requirements/{ticket_id}/clarifications", response_class=HTMLResponse)
async def clarification_form(request: Request, ticket_id: str):
    return templates.TemplateResponse(
        request,
        "clarification_form.html",
        {
            "ticket_id": ticket_id,
            "questions": get_clarification_questions(ticket_id),
        },
    )


@router.post("/requirements/{ticket_id}/clarifications")
async def submit_clarification_answers(request: Request, ticket_id: str):
    form = await request.form()
    answers = {}

    for key, value in form.items():
        if key.startswith("answer__"):
            question_id = key.replace("answer__", "", 1)
            answers.setdefault(question_id, {})["answer"] = str(value)
        elif key.startswith("option__"):
            question_id = key.replace("option__", "", 1)
            answers.setdefault(question_id, {})["selected_option_key"] = str(value)
        elif key.startswith("custom_answer__"):
            question_id = key.replace("custom_answer__", "", 1)
            answers.setdefault(question_id, {})["custom_answer"] = str(value)

    save_clarification_answers(ticket_id=ticket_id, answers=answers)
    return _redirect_detail(
        ticket_id,
        tab="clarifications",
        success="Clarification answers saved.",
        anchor="clarifications",
    )


@router.post("/requirements/{ticket_id}/structure/generate")
async def generate_structure(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="generate_structure",
        job_callable=lambda: generate_structure_for_web(
            ticket_id,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", structure_version="latest")


@router.post("/requirements/{ticket_id}/structure/self-review")
async def self_review_structure(
    ticket_id: str,
    structure_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="self_review_structure",
        job_callable=lambda: self_review_structure_version(
            ticket_id,
            structure_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(
        ticket_id,
        tab="design",
        structure_version=structure_version,
    )


@router.post("/requirements/{ticket_id}/structure/improve-ai")
async def improve_structure_ai(
    ticket_id: str,
    structure_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    new_version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_structure_ai",
        job_callable=lambda: improve_structure_from_ai_review(
            ticket_id,
            structure_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", structure_version=new_version)


@router.post("/requirements/{ticket_id}/structure/improve-human")
async def improve_structure_human(
    ticket_id: str,
    structure_version: str = Form(...),
    human_review_comment: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    new_version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_structure_human",
        job_callable=lambda: improve_structure_from_comment(
            ticket_id=ticket_id,
            version=structure_version,
            comment=human_review_comment,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", structure_version=new_version)


@router.post("/requirements/{ticket_id}/structure/save")
async def save_structure_version(
    ticket_id: str,
    structure_json: str = Form(...),
):
    new_version = save_structure_json_as_new_version(ticket_id, structure_json)
    return _redirect_detail(ticket_id, tab="design", structure_version=new_version)


@router.post("/requirements/{ticket_id}/structure/approve")
async def approve_selected_structure(
    ticket_id: str,
    structure_version: str = Form(...),
):
    approve_structure_version(ticket_id, structure_version)
    return _redirect_detail(ticket_id, tab="design", structure_version="approved")


@router.get("/requirements/{ticket_id}/structure/excel")
async def download_structure_excel(
    ticket_id: str,
    structure_version: str = "latest",
):
    excel_file = export_structure_version_to_excel(ticket_id, structure_version)
    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/requirements/{ticket_id}/scenarios/generate")
async def generate_scenarios_for_web(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="generate_scenarios",
        job_callable=lambda: generate_scope_and_scenarios(
            ticket_id,
            ai_mode=ai_mode,
            source_channel="web",
        ),
    )
    return _redirect_detail(ticket_id, tab="design", scenario_version=version)


@router.post("/requirements/{ticket_id}/scenarios/coverage-review")
async def coverage_review_for_web(
    ticket_id: str,
    scenario_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="coverage_review",
        job_callable=lambda: run_scenario_coverage_review(
            ticket_id,
            scenario_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(
        ticket_id,
        tab="design",
        scenario_version=scenario_version,
    )


@router.post("/requirements/{ticket_id}/scenarios/improve-ai")
async def improve_scenarios_ai(
    ticket_id: str,
    scenario_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_scenarios_ai",
        job_callable=lambda: improve_scenarios_from_ai_review(
            ticket_id,
            scenario_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", scenario_version=version)


@router.post("/requirements/{ticket_id}/scenarios/improve-human")
async def improve_scenarios_human(
    ticket_id: str,
    scenario_version: str = Form(...),
    human_review_comment: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_scenarios_human",
        job_callable=lambda: improve_scenarios_from_human_review(
            ticket_id,
            scenario_version,
            human_review_comment,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", scenario_version=version)


@router.post("/requirements/{ticket_id}/scenarios/approve")
async def approve_scenarios_for_web(
    ticket_id: str,
    scenario_version: str = Form(...),
):
    approve_scenarios(ticket_id, scenario_version)
    return _redirect_detail(ticket_id, tab="design", scenario_version="approved")


@router.post("/requirements/{ticket_id}/testcases/generate")
async def generate_testcases_for_web(
    ticket_id: str,
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    try:
        version = await _run_ticket_job(
            ticket_id=ticket_id,
            action="generate_testcases",
            job_callable=lambda: generate_testcases_from_approved_scenarios(
                ticket_id,
                ai_mode=ai_mode,
                source_channel="web",
            ),
        )
    except ValueError as error:
        return _redirect_detail(
            ticket_id,
            tab="design",
            error=str(error),
        )

    return _redirect_detail(
        ticket_id,
        tab="design",
        testcase_version=version,
    )


@router.post("/requirements/{ticket_id}/testcases/final-review")
async def final_review_for_web(
    ticket_id: str,
    testcase_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    await _run_ticket_job(
        ticket_id=ticket_id,
        action="final_review",
        job_callable=lambda: run_final_review(
            ticket_id,
            testcase_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(
        ticket_id,
        tab="design",
        testcase_version=testcase_version,
    )


@router.post("/requirements/{ticket_id}/testcases/improve-ai")
async def improve_testcases_ai(
    ticket_id: str,
    testcase_version: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_testcases_ai",
        job_callable=lambda: improve_testcases_from_ai_review(
            ticket_id,
            testcase_version,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", testcase_version=version)


@router.post("/requirements/{ticket_id}/testcases/improve-human")
async def improve_testcases_human(
    ticket_id: str,
    testcase_version: str = Form(...),
    human_review_comment: str = Form(...),
    _: None = Depends(portal_ai_mode_dependency),
):
    ai_mode = (get_current_portal_ai_mode() or {}).get("ai_mode")
    version = await _run_ticket_job(
        ticket_id=ticket_id,
        action="improve_testcases_human",
        job_callable=lambda: improve_testcases_from_human_review(
            ticket_id,
            testcase_version,
            human_review_comment,
            ai_mode=ai_mode,
        ),
    )
    return _redirect_detail(ticket_id, tab="design", testcase_version=version)


@router.post("/requirements/{ticket_id}/testcases/save")
async def save_testcases_version(
    ticket_id: str,
    testcases_json: str = Form(...),
):
    version = save_testcases_json_as_new_version(ticket_id, testcases_json)
    return _redirect_detail(ticket_id, tab="design", testcase_version=version)


@router.post("/requirements/{ticket_id}/testcases/approve")
async def approve_testcases_for_web(
    ticket_id: str,
    testcase_version: str = Form(...),
):
    approve_testcases(ticket_id, testcase_version)
    return _redirect_detail(ticket_id, tab="design", testcase_version="approved")


@router.post("/requirements/{ticket_id}/testcases/feedback")
async def submit_testcase_feedback(
    ticket_id: str,
    testcase_version: str = Form(...),
    test_case_id: str = Form(...),
    action: str = Form(...),
    reason_code: str = Form(""),
    user_identity: str = Form(...),
    comment: str = Form(""),
    edited_testcase_json: str = Form(""),
):
    cases = get_testcases(ticket_id, testcase_version)
    original = next(
        (
            item for item in cases
            if str(item.get("test_case_id") or item.get("testcase_id") or item.get("id") or "") == test_case_id
        ),
        None,
    )
    if original is None:
        return _redirect_detail(ticket_id, tab="design", testcase_version=testcase_version, error=f"Test case {test_case_id!r} was not found in the selected version.")
    try:
        edited = json.loads(edited_testcase_json) if edited_testcase_json.strip() else None
        record_testcase_feedback(
            ticket_id=ticket_id,
            test_case_id=test_case_id,
            testcase_version=testcase_version,
            action=action,
            original_content=original,
            edited_content=edited,
            user=user_identity,
            reason_codes=[reason_code] if reason_code else [],
            comment=comment or None,
        )
    except (PermissionError, ValueError, json.JSONDecodeError) as error:
        return _redirect_detail(ticket_id, tab="design", testcase_version=testcase_version, error=str(error))
    return _redirect_detail(ticket_id, tab="design", testcase_version=testcase_version, success="QA feedback recorded.")


@router.post("/requirements/{ticket_id}/testcases/export-override")
async def override_testcase_export_gate(
    ticket_id: str,
    testcase_version: str = Form(...),
    export_format: str = Form("function_based_xlsx"),
    reason: str = Form(...),
    user_identity: str = Form(...),
    affected_blocker_ids: str = Form(...),
    scope: str = Form(...),
):
    testcases = (
        get_incremental_testcases(ticket_id)
        if export_format == "incremental_xlsx"
        else get_testcases(ticket_id, testcase_version)
    )
    try:
        create_export_override(
            ticket_id=ticket_id,
            testcases=testcases,
            testcase_version=testcase_version,
            export_format=export_format,
            reason=reason,
            user_identity=user_identity,
            affected_blocker_ids=[
                item.strip() for item in affected_blocker_ids.split(",") if item.strip()
            ],
            scope=scope,
        )
    except (PermissionError, ValueError) as error:
        return _redirect_detail(
            ticket_id,
            tab="analysis" if export_format == "incremental_xlsx" else "design",
            testcase_version=(
                "latest" if export_format == "incremental_xlsx" else testcase_version
            ),
            error=str(error),
        )
    return _redirect_detail(
        ticket_id,
        tab="analysis" if export_format == "incremental_xlsx" else "design",
        testcase_version=(
            "latest" if export_format == "incremental_xlsx" else testcase_version
        ),
        success="Export override recorded.",
    )


@router.get("/requirements/{ticket_id}/testcases/excel")
async def download_testcases_excel(
    ticket_id: str,
    testcase_version: str = "latest",
):
    try:
        excel_file = export_testcases_excel(ticket_id, testcase_version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/requirements/{ticket_id}/testcases/incremental-excel")
async def download_incremental_testcases_excel(ticket_id: str):
    try:
        _ensure_jira_requirement(ticket_id)
        excel_file = export_incremental_testcases_excel(ticket_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/requirements/{ticket_id}/scenarios/excel")
async def download_scenarios_excel(
    ticket_id: str,
    scenario_version: str = "latest",
):
    excel_file = export_scenarios_excel(
        ticket_id=ticket_id,
        version=scenario_version,
    )

    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _dispatch_portal_job(
    ticket_id: str,
    action: str,
    ai_mode_context: dict[str, Any] | None,
    job_callable,
    job_id: str,
) -> None:
    def _background():
        try:
            asyncio.run(
                run_portal_ticket_job(
                    ticket_id=ticket_id,
                    action=action,
                    ai_mode_context=ai_mode_context,
                    job_callable=job_callable,
                    job_id=job_id,
                )
            )
        except Exception:
            pass

    thread = threading.Thread(target=_background, daemon=True)
    thread.start()


def _check_incremental_safety(ticket_id: str) -> None:
    """Load the regeneration plan and raise HTTPException if safety blocks incremental action.

    Does **not** call any LLM.
    """
    plan = load_latest_regeneration_plan(ticket_id)
    if not plan:
        return  # no plan yet – the downstream service will raise a clearer error

    safety = plan.get("safety", {})
    status = safety.get("overall_status", "")
    reasons = safety.get("safety_reasons", [])

    if status == SAFETY_FULL_RECOMMENDED:
        msg = (
            "Incremental regeneration is blocked by safety rules.\n"
            "Status: FULL_REGENERATE_RECOMMENDED.\n"
        )
        if reasons:
            msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
        msg += "\n\nRun a full regenerate instead."
        raise HTTPException(status_code=400, detail=msg)

    if status == SAFETY_MANUAL_REVIEW:
        msg = (
            "Incremental regeneration is blocked by safety rules.\n"
            "Status: MANUAL_REVIEW_RECOMMENDED.\n"
        )
        if reasons:
            msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
        msg += "\n\nManual review is required before proceeding."
        raise HTTPException(status_code=400, detail=msg)


def _ensure_jira_requirement(ticket_id: str) -> None:
    if not requirement_is_jira(ticket_id):
        raise ValueError(JIRA_SYNC_NOT_AVAILABLE)


async def _run_ticket_job(ticket_id: str, action: str, job_callable):
    ai_mode_context = get_current_portal_ai_mode()
    ai_mode = (ai_mode_context or {}).get("ai_mode")

    # Provider safety check handles NO_LLM, TEST_LOCAL_ONLY unavailable, etc.
    try:
        check_provider_safety(ai_mode_context)
    except RuntimeError as error:
        raise HTTPException(
            status_code=400,
            detail=format_provider_error(
                error=error,
                ai_mode=ai_mode,
                source_channel="portal",
            ),
        ) from error

    try:
        return await run_portal_ticket_job(
            ticket_id=ticket_id,
            action=action,
            ai_mode_context=ai_mode_context,
            job_callable=job_callable,
        )
    except (PortalConcurrencyError, PortalJobBusyError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=400,
            detail=format_provider_error(
                error=error,
                ai_mode=ai_mode,
                source_channel="portal",
            ),
        ) from error
