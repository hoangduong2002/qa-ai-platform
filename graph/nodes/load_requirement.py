from app.services.requirement_service import (
    get_requirement_service
)

from app.utils.clarification_session import (
    load_clarification_answers
)


def load_requirement(state):

    service = get_requirement_service()

    data = service.load_requirement(
        state["ticket_id"]
    )

    clarification_answers = load_clarification_answers(
        state["ticket_id"]
    )

    clarification_text = ""

    if clarification_answers:
        clarification_text = f"""

Clarification Answers:
{clarification_answers.get("raw_answers", "")}
"""

    requirement_context = f"""
Summary:
{data["ticket"].get("summary", "")}

Description:
{data["description"]}

Comments:
{data["comments"]}

{clarification_text}
"""

    return {
        "requirement_context": requirement_context
    }