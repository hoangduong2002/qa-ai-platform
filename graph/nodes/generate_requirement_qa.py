import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import (
    save_requirement_qa
)


def generate_requirement_qa(
    state
):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_requirement_qa.md"
    )

    final_prompt = prompt.replace(
        "{analysis}",
        json.dumps(
            state.get(
                "analysis",
                {}
            ),
            indent=2,
            ensure_ascii=False
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="generate_requirement_qa"
    )

    try:

        qa = parse_json(
            response.content
        )
        
        save_requirement_qa(
            state["ticket_id"],
            qa
        )

    except Exception:

        qa = {
            "raw_response":
            response.content
        }

    return {
        "requirement_qa": qa
    }