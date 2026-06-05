import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json

from app.utils.file_writer import (
    save_requirement_summary
)

from app.utils.clarification_session import (
    load_clarification_answers
)


def generate_requirement_summary(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_requirement_summary.md"
    )

    clarification_answers = load_clarification_answers(
        state["ticket_id"]
    )

    answered_clarifications = (
        clarification_answers.get(
            "answered_clarifications",
            []
        )
    )

    final_prompt = (
        prompt
        .replace(
            "{analysis}",
            json.dumps(
                state.get("analysis", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{clarifications}",
            json.dumps(
                state.get("clarifications", {}),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{clarification_answers}",
            json.dumps(
                answered_clarifications,
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="generate_requirement_summary"
    )

    try:
        summary = parse_json(
            response.content
        )

        save_requirement_summary(
            state["ticket_id"],
            summary
        )

    except Exception:
        summary = {
            "raw_response": response.content
        }

    return {
        "requirement_summary": summary
    }