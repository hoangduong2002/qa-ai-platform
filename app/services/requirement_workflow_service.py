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

async def run_requirement_summary(
    ticket_id: str
):
    requirement_summary_graph.invoke(
        {
            "ticket_id": ticket_id
        }
    )

    return load_ticket_artifacts(ticket_id)


async def run_requirement_questions(
    ticket_id: str
):
    result = requirement_question_graph.invoke(
        {
            "ticket_id": ticket_id
        }
    )

    save_clarification_questions_snapshot(
        ticket_id,
        result.get("clarifications", {})
    )

    return result