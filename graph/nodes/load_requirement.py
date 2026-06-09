from app.services.requirement_service import (
    get_requirement_service,
)

from app.services.requirement_sanitization_service import (
    sanitize_requirement_for_analysis,
)


def load_requirement(state):
    ticket_id = state["ticket_id"]

    service = get_requirement_service()

    data = service.load_requirement(
        ticket_id
    )

    requirement_context = f"""
Summary:
{data["ticket"].get("summary", "")}

Description:
{data["description"]}

Comments:
{data["comments"]}

Additional Notes:
{data.get("additional_notes", "")}

Uploaded Documents:
{data.get("uploaded_content", "")}

Clarification Answer Notes:
{data.get("clarification_answer_notes", "")}
"""

    sanitized_requirement_context = sanitize_requirement_for_analysis(
        ticket_id=ticket_id,
        raw_requirement=requirement_context,
    )

    return {
        "requirement_context": sanitized_requirement_context
    }