from app.application.response_models import AppAction, AppResult
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.test_structure_store import (
    has_test_case_structure,
    has_approved_test_case_structure,
    load_structure_session,
    load_approved_test_case_structure,
)
from app.services.test_structure_service import (
    run_initial_structure_flow,
    resume_structure_review,
)


def _structure_actions(ticket_id: str) -> list[AppAction]:
    return [
        AppAction(
            label="AI Review",
            action="structure_self_review",
            ticket_id=ticket_id,
        ),
        AppAction(
            label="Comment",
            action="structure_comment",
            ticket_id=ticket_id,
        ),
        AppAction(
            label="Wait",
            action="structure_wait",
            ticket_id=ticket_id,
        ),
        AppAction(
            label="Approve",
            action="structure_approve",
            ticket_id=ticket_id,
        ),
    ]


def _extract_main_functions(structure: dict) -> list:
    if not isinstance(structure, dict):
        return []

    functions = (
        structure.get("main_functions")
        or structure.get("functions")
        or structure.get("test_functions")
        or []
    )

    if not isinstance(functions, list):
        return []

    return functions


def _build_structure_message(
    ticket_id: str,
    state: dict,
    is_resume: bool,
) -> str:
    session = load_structure_session(ticket_id)
    review = state.get("test_case_structure_review", {})
    structure_data = state.get("test_case_structure", {})

    main_functions = _extract_main_functions(structure_data)

    title = (
        "Resuming test case structure review"
        if is_resume
        else "Test case structure ready"
    )

    return (
        f"{title} for {ticket_id}\n\n"
        f"Version: {session.get('current_version')}\n"
        f"Review Iterations: "
        f"{session.get('review_iterations')}/"
        f"{session.get('max_review_iterations')}\n"
        f"AI Coverage Score: {review.get('coverage_score', 'N/A')}\n"
        f"AI Approved: {review.get('approved_by_ai', False)}\n"
        f"Main Functions: {len(main_functions)}\n\n"
        f"Please review and approve the structure before generating test cases."
    )


def build_structured_generation_state(ticket_id: str) -> dict:
    """
    Build the state required by the structured test generation graph.

    This function is intentionally separated from Telegram so FastAPI/Teams
    can reuse the same logic later.
    """

    approved_structure = load_approved_test_case_structure(ticket_id)

    if not approved_structure:
        raise ValueError(
            f"No approved test case structure found for {ticket_id}. "
            f"Please approve the structure before generating test cases."
        )

    artifacts = load_ticket_artifacts(ticket_id)

    artifacts["ticket_id"] = ticket_id
    artifacts["generation_mode"] = "STRUCTURED_FUNCTION_BASED"
    artifacts["approved_test_case_structure"] = approved_structure

    return artifacts


def prepare_generation(ticket_id: str) -> AppResult:
    """
    Structure-first generation gate.

    Rules:
    1. Approved structure exists:
       allow structured generation.
    2. Structure exists but not approved:
       resume structure review.
    3. No structure:
       create structure, run AI review/improve, export Excel,
       then wait for human approval.
    """

    if has_approved_test_case_structure(ticket_id):
        approved_structure = load_approved_test_case_structure(ticket_id)
        main_functions = _extract_main_functions(approved_structure)

        return AppResult(
            status="READY_TO_GENERATE",
            message=(
                f"Approved test case structure found for {ticket_id}.\n"
                f"Generation Mode: STRUCTURED_FUNCTION_BASED\n"
                f"Main Functions: {len(main_functions)}\n\n"
                f"Generating test cases from approved structure..."
            ),
            data={
                "ticket_id": ticket_id,
                "generation_mode": "STRUCTURED_FUNCTION_BASED",
                "approved_test_case_structure": approved_structure,
            },
        )

    if has_test_case_structure(ticket_id):
        state = resume_structure_review(ticket_id)

        return AppResult(
            status="WAITING_STRUCTURE_APPROVAL",
            message=_build_structure_message(
                ticket_id=ticket_id,
                state=state,
                is_resume=True,
            ),
            files=[state["structure_excel_file"]],
            actions=_structure_actions(ticket_id),
            data=state,
        )

    state = run_initial_structure_flow(ticket_id)

    return AppResult(
        status="WAITING_STRUCTURE_APPROVAL",
        message=_build_structure_message(
            ticket_id=ticket_id,
            state=state,
            is_resume=False,
        ),
        files=[state["structure_excel_file"]],
        actions=_structure_actions(ticket_id),
        data=state,
    )