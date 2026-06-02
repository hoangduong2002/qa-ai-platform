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
"""

    return {
        "requirement_context": requirement_context
    }