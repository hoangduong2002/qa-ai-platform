from graph.requirement_question_graph import (
    requirement_question_graph
)
from graph.requirement_summary_graph import (
    requirement_summary_graph
)
from app.utils.artifact_loader import (
    load_ticket_artifacts
)
from app.utils.clarification_session import (
    save_clarification_questions_snapshot
)
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)


def _current_ai_mode() -> str | None:
    mode = get_current_portal_ai_mode()

    if not mode:
        return None

    return mode.get("ai_mode")

async def run_requirement_summary(
    ticket_id: str
):
    state = {
        "ticket_id": ticket_id,
    }
    ai_mode = _current_ai_mode()

    if ai_mode:
        state["ai_mode"] = ai_mode

    requirement_summary_graph.invoke(state)

    return load_ticket_artifacts(ticket_id)


async def run_requirement_questions(
    ticket_id: str
):
    state = {
        "ticket_id": ticket_id,
    }
    ai_mode = _current_ai_mode()

    if ai_mode:
        state["ai_mode"] = ai_mode

    result = requirement_question_graph.invoke(state)

    save_clarification_questions_snapshot(
        ticket_id,
        result.get("clarifications", {})
    )

    return result
