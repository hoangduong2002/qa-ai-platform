from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import (
    save_analysis,
    save_requirement_items
)
from app.utils.llm_json import parse_json


def analyze_requirement(state):
    metadata = state.get("requirement_context_metadata") or {}

    if metadata:
        print(
            "analyze_requirement context_source="
            f"{metadata.get('context_source')}, "
            f"length={metadata.get('context_length')}, "
            f"path={metadata.get('context_path')}"
        )

    llm = get_llm()

    prompt = load_prompt(
        "prompts/analyze_requirement.md"
    )

    final_prompt = prompt.replace(
        "{requirement_context}",
        state.get("requirement_context", "")
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="analyze_requirement"
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
