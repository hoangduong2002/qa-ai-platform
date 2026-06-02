import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import (
    save_analysis,
    save_requirement_items
)
from app.utils.llm_json import parse_json


def analyze_requirement(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/analyze_requirement.md"
    )

    final_prompt = prompt.replace(
        "{requirement_context}",
        state["requirement_context"]
    )

    response = llm.invoke(
        final_prompt
    )

    try:

        analysis = parse_json(
            response.content
        )

        save_analysis(
            state["ticket_id"],
            analysis
        )

        requirement_items = analysis.get(
            "requirement_items",
            []
        )

        save_requirement_items(
            state["ticket_id"],
            requirement_items
        )

    except Exception:

        analysis = {
            "raw_response": response.content
        }

    return {
        "analysis": analysis
    }