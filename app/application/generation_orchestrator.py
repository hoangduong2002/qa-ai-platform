from app.application.response_models import (
    AppAction,
    AppResult
)

from app.utils.test_structure_store import (
    has_test_case_structure,
    has_approved_test_case_structure,
    load_structure_session
)

from app.services.test_structure_service import (
    run_initial_structure_flow,
    resume_structure_review
)


def _structure_actions(
    ticket_id: str
) -> list[AppAction]:

    return [
        AppAction(
            label="Self Review",
            action="structure_self_review",
            ticket_id=ticket_id
        ),
        AppAction(
            label="Comment",
            action="structure_comment",
            ticket_id=ticket_id
        ),
        AppAction(
            label="Wait",
            action="structure_wait",
            ticket_id=ticket_id
        ),
        AppAction(
            label="Approve",
            action="structure_approve",
            ticket_id=ticket_id
        )
    ]


def _build_structure_message(
    ticket_id: str,
    state: dict,
    is_resume: bool
) -> str:

    session = load_structure_session(
        ticket_id
    )

    review = state.get(
        "test_case_structure_review",
        {}
    )

    structure_data = state.get(
        "test_case_structure",
        {}
    )

    main_functions = structure_data.get(
        "main_functions",
        []
    )

    title = (
        "Resuming test case structure review"
        if is_resume
        else "Test Case Structure ready"
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


def prepare_generation(
    ticket_id: str
) -> AppResult:

    if has_approved_test_case_structure(
        ticket_id
    ):
        return AppResult(
            status="READY_TO_GENERATE",
            message=(
                f"Approved test case structure found for {ticket_id}.\n"
                f"Generating testcases..."
            ),
            data={
                "ticket_id": ticket_id
            }
        )

    if has_test_case_structure(
        ticket_id
    ):
        state = resume_structure_review(
            ticket_id
        )

        return AppResult(
            status="WAITING_STRUCTURE_APPROVAL",
            message=_build_structure_message(
                ticket_id,
                state,
                is_resume=True
            ),
            files=[
                state["structure_excel_file"]
            ],
            actions=_structure_actions(
                ticket_id
            ),
            data=state
        )

    state = run_initial_structure_flow(
        ticket_id
    )

    return AppResult(
        status="WAITING_STRUCTURE_APPROVAL",
        message=_build_structure_message(
            ticket_id,
            state,
            is_resume=False
        ),
        files=[
            state["structure_excel_file"]
        ],
        actions=_structure_actions(
            ticket_id
        ),
        data=state
    )