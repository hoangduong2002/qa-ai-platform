import os
import logging
from requests import session

from app.utils.artifact_loader import load_ticket_artifacts
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)

from graph.nodes.generate_test_case_structure import (
    generate_test_case_structure
)

from graph.nodes.review_test_case_structure import (
    review_test_case_structure
)

from graph.nodes.improve_test_case_structure import (
    improve_test_case_structure
)

from app.utils.test_structure_exporter import (
    export_test_case_structure_to_excel
)

from app.utils.test_structure_store import (
    load_structure_session,
    save_structure_session,
    save_test_case_structure_version,
    save_test_case_structure_review_version,
    save_latest_test_case_structure,
    load_latest_test_case_structure,
    save_approved_test_case_structure
)

from app.utils.test_structure_store import (
    load_latest_test_case_structure,
    load_structure_session
)

from app.utils.test_structure_exporter import (
    export_test_case_structure_to_excel
)


def resume_structure_review(
    ticket_id: str
):
    structure = load_latest_test_case_structure(
        ticket_id
    )

    session = load_structure_session(
        ticket_id
    )

    state = {
        "ticket_id": ticket_id,
        "test_case_structure": structure,
        "test_case_structure_review": {}
    }

    excel_file = export_test_case_structure_to_excel(
        ticket_id,
        structure,
        {}
    )

    state["structure_excel_file"] = excel_file
    state["structure_session"] = session

    return state



def _export_structure(ticket_id: str, state: dict):
    excel_file = export_test_case_structure_to_excel(
        ticket_id,
        state.get("test_case_structure", {}),
        state.get("test_case_structure_review", {})
    )

    state["structure_excel_file"] = excel_file

    return state


def _apply_ai_state(
    state: dict,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> dict:
    if ai_mode:
        state["ai_mode"] = ai_mode
    else:
        portal_ai_mode = get_current_portal_ai_mode()

        if portal_ai_mode and portal_ai_mode.get("ai_mode"):
            state["ai_mode"] = portal_ai_mode["ai_mode"]

    if source_channel:
        state["source_channel"] = source_channel

    return state


def run_initial_structure_flow(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    """
    Initial structure generation flow.

    MVP optimized behavior:
    - Generate test case structure only.
    - Do NOT run automatic AI self review.
    - Do NOT run automatic AI improve.
    - Export the generated structure for human review.
    - User can manually choose Self Review / Comment / Approve later.

    This reduces token usage significantly.
    """

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id

    if (source_channel or "").strip().lower() == "telegram" and not ai_mode:
        raise RuntimeError(
            "Telegram structure generation missing ai_mode. "
            "This is a propagation bug."
        )

    _apply_ai_state(state, ai_mode, source_channel)

    structure_result = generate_test_case_structure(state)
    state.update(structure_result)

    test_case_structure = state.get("test_case_structure")

    if not test_case_structure:
        raise ValueError(
            f"Failed to generate test case structure for {ticket_id}."
        )

    version = "v1"

    save_test_case_structure_version(
        ticket_id,
        test_case_structure,
        version,
    )

    save_latest_test_case_structure(
        ticket_id,
        test_case_structure,
    )

    session = {
        "current_version": version,
        "review_iterations": 0,
        "max_review_iterations": int(
            os.getenv("MAX_STRUCTURE_REVIEW_ITERATIONS", "3")
        ),
        "approved": False,
        "waiting_human_review": True,
        "last_review_version": "",
        "review_mode": "MANUAL_REVIEW_REQUIRED",
    }

    save_structure_session(ticket_id, session)

    state["structure_session"] = session
    state["current_version"] = version

    # No AI review is generated in the initial flow.
    # This placeholder keeps exporters/renderers safe if they expect the key.
    state["test_case_structure_review"] = {
        "review_mode": "NOT_REVIEWED",
        "coverage_score": "",
        "approved_by_ai": False,
        "summary": (
            "Structure was generated but not reviewed automatically. "
            "Use Self Review if you want AI to review it."
        ),
        "issues": [],
        "recommendations": [],
    }

    return _export_structure(ticket_id, state)


def run_structure_self_review(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    session = load_structure_session(ticket_id)

    if session.get("approved"):
        raise ValueError("Structure is already approved.")

    current_iteration = session.get("review_iterations", 0)
    max_iterations = session.get("max_review_iterations", 3)

    if current_iteration >= max_iterations:
        raise ValueError("Maximum structure review iterations reached.")

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["test_case_structure"] = load_latest_test_case_structure(ticket_id)
    state["structure_review_comments"] = []
    _apply_ai_state(state, ai_mode, source_channel)

    if not state["test_case_structure"]:
        raise ValueError(
            f"No latest test case structure found for {ticket_id}."
        )

    review_result = review_test_case_structure(state)
    state.update(review_result)

    current_version = session.get("current_version") or "v0"

    save_test_case_structure_review_version(
        ticket_id,
        state["test_case_structure_review"],
        current_version,
    )

    session["last_review_version"] = current_version
    session["waiting_human_review"] = True

    save_structure_session(ticket_id, session)

    return _export_structure(ticket_id, state)


def _get_next_structure_version(session: dict) -> str:
    current_version = session.get("current_version") or "v0"

    try:
        current_number = int(str(current_version).replace("v", ""))
    except ValueError:
        current_number = 0

    return f"v{current_number + 1}"


def _next_structure_version(
    current_version: str,
) -> str:
    try:
        number = int(
            current_version.replace("v", "")
        )
    except Exception:
        number = 1

    return f"v{number + 1}"


def run_structure_comment_improve(
    ticket_id: str,
    comment: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    state = load_ticket_artifacts(ticket_id)

    latest_structure = load_latest_test_case_structure(
        ticket_id
    )

    if not latest_structure:
        raise ValueError(
            f"No latest test case structure found for {ticket_id}"
        )

    session = load_structure_session(
        ticket_id
    )

    current_version = session.get(
        "current_version",
        "v1",
    )

    state["ticket_id"] = ticket_id
    state["test_case_structure"] = latest_structure
    state["structure_review_comments"] = [
        comment,
    ]
    _apply_ai_state(state, ai_mode, source_channel)

    improve_result = improve_test_case_structure(
        state
    )

    state.update(
        improve_result
    )

    improved_structure = state.get(
        "test_case_structure"
    )

    if not improved_structure:
        raise ValueError(
            "Improve structure failed: no improved structure returned."
        )

    next_version = _next_structure_version(
        current_version
    )

    save_test_case_structure_version(
        ticket_id=ticket_id,
        structure=improved_structure,
        version=next_version,
    )

    save_latest_test_case_structure(
        ticket_id=ticket_id,
        structure=improved_structure,
    )

    session["current_version"] = next_version
    session["approved"] = False
    session["waiting_human_review"] = True
    session["last_improve_comment"] = comment

    # Important:
    # Do not auto-review after comment improve.
    # User will manually click Self Review Structure if needed.
    session.pop(
        "last_review_version",
        None,
    )

    save_structure_session(
        ticket_id,
        session,
    )

    export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=improved_structure,
        review={},
    )

    return {
        "ticket_id": ticket_id,
        "previous_version": current_version,
        "new_version": next_version,
        "test_case_structure": improved_structure,
        "structure_session": session,
    }


def approve_structure(ticket_id: str):
    structure = load_latest_test_case_structure(ticket_id)

    if not structure:
        raise ValueError("No structure found.")

    save_approved_test_case_structure(
        ticket_id,
        structure
    )

    session = load_structure_session(ticket_id)
    session["approved"] = True
    session["waiting_human_review"] = False

    save_structure_session(ticket_id, session)

    return structure


def wait_structure_review(ticket_id: str):
    session = load_structure_session(ticket_id)
    session["waiting_human_review"] = True
    save_structure_session(ticket_id, session)
    return session
