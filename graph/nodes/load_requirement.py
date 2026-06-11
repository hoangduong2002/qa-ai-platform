from app.services.requirement_service import (
    get_requirement_service,
)

from app.services.requirement_sanitization_service import (
    sanitize_requirement_for_analysis,
)
from app.utils.requirement_context_loader import (
    load_requirement_context_for_llm,
)


def load_requirement(state):
    ticket_id = state["ticket_id"]

    compact_requirement_context, context_metadata = load_requirement_context_for_llm(
        ticket_id
    )

    if context_metadata.get("context_source") == "compact" and compact_requirement_context:
        return {
            "requirement_context": compact_requirement_context,
            "requirement_context_metadata": context_metadata,
        }

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
        "requirement_context": sanitized_requirement_context,
        "requirement_context_metadata": {
            **context_metadata,
            "context_length": len(sanitized_requirement_context),
        },
    }
