from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.requirement_workflow_service import (
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
    create_requirement_from_jira_and_sanitize,
    delete_requirement,
    export_requirement_analysis_to_excel,
    export_requirement_summary_to_excel,
    get_clarification_questions,
    get_requirement_detail,
    list_requirements,
    sanitize_existing_requirement,
    save_clarification_answers,
    update_requirement,
)
from app.services.web_test_design_artifact_service import (
    approve_scenarios,
    approve_testcases,
    export_testcases_excel,
    generate_scope_and_scenarios,
    generate_testcases_from_approved_scenarios,
    get_coverage_review,
    get_coverage_review_json,
    get_final_review,
    get_final_review_json,
    get_scenarios_json,
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
)

BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(prefix="/portal", tags=["Web Portal"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_detail(ticket_id: str, tab: str = "analysis", **params):
    query = [f"tab={tab}"]
    for key, value in params.items():
        if value is not None:
            query.append(f"{key}={value}")

    return RedirectResponse(
        url=f"/portal/requirements/{ticket_id}?{'&'.join(query)}",
        status_code=303,
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"requirements": list_requirements()},
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
async def create_requirement_from_jira(issue_key: str = Form(...)):
    ticket_id = create_requirement_from_jira_and_sanitize(issue_key=issue_key)
    return RedirectResponse(url=f"/portal/requirements/{ticket_id}", status_code=303)


@router.get("/requirements/{ticket_id}", response_class=HTMLResponse)
async def requirement_detail(
    request: Request,
    ticket_id: str,
    tab: str | None = None,
    structure_version: str = "latest",
    scenario_version: str = "latest",
    testcase_version: str = "latest",
):
    detail = get_requirement_detail(ticket_id)

    structure_session = get_structure_session_for_web(ticket_id)
    scenario_session = load_scenario_session(ticket_id)
    testcase_session = load_testcase_session(ticket_id)

    if tab not in ["analysis", "design"]:
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
    selected_testcases_json = get_testcases_json(ticket_id, testcase_version)
    selected_final_review = get_final_review(ticket_id, testcase_version)

    detail.update(
        {
            "tab": tab,
            "structure_version": structure_version,
            "scenario_version": scenario_version,
            "testcase_version": testcase_version,
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
            "selected_final_review": selected_final_review,
            "selected_final_review_json": get_final_review_json(
                ticket_id,
                testcase_version,
            ),
            "has_testcase_structure": bool(selected_structure_json),
            "has_approved_structure": bool(structure_session.get("approved")),
            "has_scenarios": bool(selected_scenarios_json),
            "has_approved_scenarios": bool(scenario_session.get("approved")),
            "has_testcases": bool(selected_testcases_json),
            "has_approved_testcases": bool(testcase_session.get("approved")),
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


@router.post("/requirements/{ticket_id}/analyze")
async def analyze_requirement(ticket_id: str):
    await run_requirement_questions(ticket_id=ticket_id)
    export_requirement_analysis_to_excel(ticket_id=ticket_id)
    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/summary")
async def generate_summary(ticket_id: str):
    await run_requirement_summary(ticket_id=ticket_id)
    export_requirement_analysis_to_excel(ticket_id=ticket_id)
    return _redirect_detail(ticket_id)


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
            answers[key.replace("answer__", "", 1)] = str(value)

    save_clarification_answers(ticket_id=ticket_id, answers=answers)
    return _redirect_detail(ticket_id)


@router.post("/requirements/{ticket_id}/structure/generate")
async def generate_structure(ticket_id: str):
    generate_structure_for_web(ticket_id)
    return _redirect_detail(ticket_id, tab="design", structure_version="latest")


@router.post("/requirements/{ticket_id}/structure/self-review")
async def self_review_structure(
    ticket_id: str,
    structure_version: str = Form(...),
):
    self_review_structure_version(ticket_id, structure_version)
    return _redirect_detail(
        ticket_id,
        tab="design",
        structure_version=structure_version,
    )


@router.post("/requirements/{ticket_id}/structure/improve-ai")
async def improve_structure_ai(
    ticket_id: str,
    structure_version: str = Form(...),
):
    new_version = improve_structure_from_ai_review(ticket_id, structure_version)
    return _redirect_detail(ticket_id, tab="design", structure_version=new_version)


@router.post("/requirements/{ticket_id}/structure/improve-human")
async def improve_structure_human(
    ticket_id: str,
    structure_version: str = Form(...),
    human_review_comment: str = Form(...),
):
    new_version = improve_structure_from_comment(
        ticket_id=ticket_id,
        version=structure_version,
        comment=human_review_comment,
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
async def generate_scenarios_for_web(ticket_id: str):
    version = generate_scope_and_scenarios(ticket_id)
    return _redirect_detail(ticket_id, tab="design", scenario_version=version)


@router.post("/requirements/{ticket_id}/scenarios/coverage-review")
async def coverage_review_for_web(
    ticket_id: str,
    scenario_version: str = Form(...),
):
    run_scenario_coverage_review(ticket_id, scenario_version)
    return _redirect_detail(
        ticket_id,
        tab="design",
        scenario_version=scenario_version,
    )


@router.post("/requirements/{ticket_id}/scenarios/improve-ai")
async def improve_scenarios_ai(
    ticket_id: str,
    scenario_version: str = Form(...),
):
    version = improve_scenarios_from_ai_review(ticket_id, scenario_version)
    return _redirect_detail(ticket_id, tab="design", scenario_version=version)


@router.post("/requirements/{ticket_id}/scenarios/improve-human")
async def improve_scenarios_human(
    ticket_id: str,
    scenario_version: str = Form(...),
    human_review_comment: str = Form(...),
):
    version = improve_scenarios_from_human_review(
        ticket_id,
        scenario_version,
        human_review_comment,
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
async def generate_testcases_for_web(ticket_id: str):
    version = generate_testcases_from_approved_scenarios(ticket_id)
    return _redirect_detail(ticket_id, tab="design", testcase_version=version)


@router.post("/requirements/{ticket_id}/testcases/final-review")
async def final_review_for_web(
    ticket_id: str,
    testcase_version: str = Form(...),
):
    run_final_review(ticket_id, testcase_version)
    return _redirect_detail(
        ticket_id,
        tab="design",
        testcase_version=testcase_version,
    )


@router.post("/requirements/{ticket_id}/testcases/improve-ai")
async def improve_testcases_ai(
    ticket_id: str,
    testcase_version: str = Form(...),
):
    version = improve_testcases_from_ai_review(ticket_id, testcase_version)
    return _redirect_detail(ticket_id, tab="design", testcase_version=version)


@router.post("/requirements/{ticket_id}/testcases/improve-human")
async def improve_testcases_human(
    ticket_id: str,
    testcase_version: str = Form(...),
    human_review_comment: str = Form(...),
):
    version = improve_testcases_from_human_review(
        ticket_id,
        testcase_version,
        human_review_comment,
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


@router.get("/requirements/{ticket_id}/testcases/excel")
async def download_testcases_excel(
    ticket_id: str,
    testcase_version: str = "latest",
):
    excel_file = export_testcases_excel(ticket_id, testcase_version)
    return FileResponse(
        path=str(excel_file),
        filename=excel_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )