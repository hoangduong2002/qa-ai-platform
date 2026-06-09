from fastapi import (
    APIRouter,
    File,
    Form,
    Request,
    UploadFile,
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from fastapi.templating import Jinja2Templates

from app.services.web_requirement_service import (
    create_manual_requirement,
    create_requirement_from_jira_and_sanitize,
    delete_requirement,
    get_requirement_detail,
    list_requirements,
    sanitize_existing_requirement,
    update_requirement,
    export_requirement_summary_to_excel,
)

from app.services.requirement_workflow_service import (
    run_requirement_questions,
    run_requirement_summary,
)

from pathlib import Path
from app.services.web_requirement_service import (
    get_clarification_questions,
    save_clarification_answers,
    export_requirement_analysis_to_excel
)

from app.services.web_design_artifact_service import (
    approve_structure_version,
    export_structure_version_to_excel,
    generate_structure_for_web,
    get_structure_session_for_web,
    get_structure_version_json,
    list_structure_versions,
    save_structure_json_as_new_version,
    get_structure_review,
    get_structure_review_json,
    self_review_structure_version,
    improve_structure_with_comment_for_web,
)

from fastapi.responses import (
    FileResponse,
    RedirectResponse,
    HTMLResponse,
)

BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(
    prefix="/portal",
    tags=["Web Portal"],
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"),
)

@router.get(
    "/requirements/{ticket_id}/summary/excel",
)
async def download_requirement_summary_excel(
    ticket_id: str,
):
    excel_file = export_requirement_summary_to_excel(
        ticket_id
    )

    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@router.get(
    "",
    response_class=HTMLResponse,
)
@router.get(
    "/",
    response_class=HTMLResponse,
)
async def dashboard(
    request: Request,
):
    requirements = list_requirements()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "requirements": requirements,
        },
    )


@router.get(
    "/requirements/new",
    response_class=HTMLResponse,
)
async def new_requirement_form(
    request: Request,
):
    return templates.TemplateResponse(
        request,
        "requirement_form.html",
        {},
    )


@router.post(
    "/requirements",
)
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

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.post(
    "/requirements/from-jira",
)
async def create_requirement_from_jira(
    issue_key: str = Form(...),
):
    ticket_id = create_requirement_from_jira_and_sanitize(
        issue_key=issue_key,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.get(
    "/requirements/{ticket_id}",
    response_class=HTMLResponse,
)
async def requirement_detail(
    request: Request,
    ticket_id: str,
    tab: str = "analysis",
    structure_version: str = "latest",
    testcase_version: str = "latest",
):
    detail = get_requirement_detail(
        ticket_id
    )

    if tab not in [
        "analysis",
        "design",
    ]:
        tab = "analysis"

    structure_versions = list_structure_versions(
        ticket_id
    )

    selected_structure_json = get_structure_version_json(
        ticket_id=ticket_id,
        version=structure_version,
    )

    selected_structure_review = get_structure_review(
        ticket_id=ticket_id,
        version=structure_version,
    )

    selected_structure_review_json = get_structure_review_json(
        ticket_id=ticket_id,
        version=structure_version,
    )

    structure_session = get_structure_session_for_web(
        ticket_id
    )

    detail.update(
        {
            "tab": tab,
            "structure_version": structure_version,
            "testcase_version": testcase_version,
            "structure_versions": structure_versions,
            "selected_structure_json": selected_structure_json,
            "selected_structure_review": selected_structure_review,
            "selected_structure_review_json": selected_structure_review_json,
            "structure_session": structure_session,
            "has_testcase_structure": bool(selected_structure_json),
            "has_structure_review": bool(selected_structure_review),
            "has_approved_structure": bool(
                structure_session.get("approved")
            ),
        }
    )

    return templates.TemplateResponse(
        request,
        "requirement_detail.html",
        detail,
    )

@router.get(
    "/requirements/{ticket_id}/edit",
    response_class=HTMLResponse,
)
async def edit_requirement_form(
    request: Request,
    ticket_id: str,
):
    detail = get_requirement_detail(
        ticket_id
    )

    return templates.TemplateResponse(
        request,
        "requirement_edit.html",
        detail,
    )


@router.post(
    "/requirements/{ticket_id}/edit",
)
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

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/delete",
)
async def remove_requirement(
    ticket_id: str,
):
    delete_requirement(
        ticket_id
    )

    return RedirectResponse(
        url="/portal",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/sanitize",
)
async def sanitize_requirement(
    ticket_id: str,
):
    sanitize_existing_requirement(
        ticket_id
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/analyze",
)
async def analyze_requirement(
    ticket_id: str,
):
    await run_requirement_questions(
        ticket_id=ticket_id,
    )

    export_requirement_analysis_to_excel(
        ticket_id=ticket_id,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/summary",
)
async def generate_summary(
    ticket_id: str,
):
    await run_requirement_summary(
        ticket_id=ticket_id,
    )

    export_requirement_analysis_to_excel(
        ticket_id=ticket_id,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )
    
    
@router.get(
    "/requirements/{ticket_id}/analysis/excel",
)
async def download_requirement_analysis_excel(
    ticket_id: str,
):
    excel_file = export_requirement_analysis_to_excel(
        ticket_id=ticket_id,
    )

    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    

@router.get(
    "/requirements/{ticket_id}/clarifications",
    response_class=HTMLResponse,
)
async def clarification_form(
    request: Request,
    ticket_id: str,
):
    questions = get_clarification_questions(
        ticket_id
    )

    return templates.TemplateResponse(
        request,
        "clarification_form.html",
        {
            "ticket_id": ticket_id,
            "questions": questions,
        },
    )


@router.post(
    "/requirements/{ticket_id}/clarifications",
)
async def submit_clarification_answers(
    request: Request,
    ticket_id: str,
):
    form = await request.form()

    answers = {}

    for key, value in form.items():
        if key.startswith("answer__"):
            question_id = key.replace(
                "answer__",
                "",
                1,
            )

            answers[question_id] = str(value)

    save_clarification_answers(
        ticket_id=ticket_id,
        answers=answers,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/structure/generate",
)
async def generate_structure(
    ticket_id: str,
):
    generate_structure_for_web(
        ticket_id=ticket_id,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}?tab=design&structure_version=latest",
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/structure/save",
)
async def save_structure_version(
    ticket_id: str,
    structure_json: str = Form(...),
):
    new_version = save_structure_json_as_new_version(
        ticket_id=ticket_id,
        structure_json=structure_json,
    )

    return RedirectResponse(
        url=(
            f"/portal/requirements/{ticket_id}"
            f"?tab=design&structure_version={new_version}"
        ),
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/structure/approve",
)
async def approve_selected_structure(
    ticket_id: str,
    structure_version: str = Form(...),
):
    approve_structure_version(
        ticket_id=ticket_id,
        version=structure_version,
    )

    return RedirectResponse(
        url=(
            f"/portal/requirements/{ticket_id}"
            f"?tab=design&structure_version=approved"
        ),
        status_code=303,
    )


@router.get(
    "/requirements/{ticket_id}/structure/excel",
)
async def download_structure_excel(
    ticket_id: str,
    structure_version: str = "latest",
):
    excel_file = export_structure_version_to_excel(
        ticket_id=ticket_id,
        version=structure_version,
    )

    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post(
    "/requirements/{ticket_id}/structure/self-review",
)
async def self_review_selected_structure(
    ticket_id: str,
    structure_version: str = Form(...),
):
    self_review_structure_version(
        ticket_id=ticket_id,
        version=structure_version,
    )

    return RedirectResponse(
        url=(
            f"/portal/requirements/{ticket_id}"
            f"?tab=design&structure_version={structure_version}"
        ),
        status_code=303,
    )


@router.post(
    "/requirements/{ticket_id}/structure/comment-improve",
)
async def improve_structure_with_comment(
    ticket_id: str,
    improve_comment: str = Form(...),
):
    improve_structure_with_comment_for_web(
        ticket_id=ticket_id,
        comment=improve_comment,
    )

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}?tab=design&structure_version=latest",
        status_code=303,
    )