import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import save_clarifications
from app.utils.llm_json import parse_json


def generate_clarifications(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_clarifications.md"
    )

    final_prompt = prompt.replace(
        "{analysis}",
        json.dumps(
            state["analysis"],
            indent=2,
            ensure_ascii=False
        )
    )

    response = llm.invoke(final_prompt)

    try:
        clarifications = parse_json(
            response.content
        )

        save_clarifications(
            state["ticket_id"],
            clarifications
        )

    except Exception:
        clarifications = {
            "raw_response": response.content
        }

    return {
        "clarifications": clarifications
    }