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

from fastapi.responses import FileResponse
from fastapi.responses import FileResponse

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
):
    detail = get_requirement_detail(
        ticket_id
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