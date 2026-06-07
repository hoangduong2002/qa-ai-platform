from app.application.response_models import (
    AppAction,
    AppResult
)

from app.services.test_structure_service import (
    run_structure_self_review,
    run_structure_comment_improve,
    approve_structure as approve_structure_service,
    wait_structure_review
)

from app.utils.test_structure_store import (
    load_structure_session
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


def _build_message(
    ticket_id: str,
    state: dict,
    title: str
) -> str:

    session = load_structure_session(
        ticket_id
    )

    review = state.get(
        "test_case_structure_review",
        {}
    )

    return (
        f"{title}\n\n"
        f"Requirement: {ticket_id}\n"
        f"Version: {session.get('current_version')}\n"
        f"Review Iterations: "
        f"{session.get('review_iterations')}/"
        f"{session.get('max_review_iterations')}\n"
        f"AI Coverage Score: {review.get('coverage_score', 'N/A')}\n\n"
        f"Please choose next action."
    )


def self_review_structure(
    ticket_id: str
) -> AppResult:

    state = run_structure_self_review(
        ticket_id
    )

    return AppResult(
        status="WAITING_STRUCTURE_APPROVAL",
        message=_build_message(
            ticket_id,
            state,
            "Structure self review completed."
        ),
        files=[
            state["structure_excel_file"]
        ],
        actions=_structure_actions(
            ticket_id
        ),
        data=state
    )


def comment_improve_structure(
    ticket_id: str,
    comment: str
) -> AppResult:

    state = run_structure_comment_improve(
        ticket_id,
        comment
    )

    return AppResult(
        status="WAITING_STRUCTURE_APPROVAL",
        message=_build_message(
            ticket_id,
            state,
            "Structure updated based on your comment."
        ),
        files=[
            state["structure_excel_file"]
        ],
        actions=_structure_actions(
            ticket_id
        ),
        data=state
    )


def wait_structure(
    ticket_id: str
) -> AppResult:

    wait_structure_review(
        ticket_id
    )

    return AppResult(
        status="STRUCTURE_REVIEW_PAUSED",
        message=(
            f"Structure review paused for {ticket_id}.\n"
            f"You can resume later with:\n"
            f"/structure {ticket_id}"
        )
    )


def approve_structure(
    ticket_id: str
) -> AppResult:

    approve_structure_service(
        ticket_id
    )

    return AppResult(
        status="STRUCTURE_APPROVED",
        message=(
            f"Test case structure approved for {ticket_id}.\n\n"
            f"You can now generate test cases with:\n"
            f"/generate {ticket_id}"
        )
    )