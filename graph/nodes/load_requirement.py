from app.services.requirement_service import (
    get_requirement_service
)


def load_requirement(state):

    service = get_requirement_service()

    data = service.load_requirement(
        state["ticket_id"]
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

    return {
        "requirement_context": requirement_context
    }