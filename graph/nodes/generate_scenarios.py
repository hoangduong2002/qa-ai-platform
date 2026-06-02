import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.scenario_writer import save_scenarios


def generate_scenarios(state):
    
    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_scenarios.md"
    )

    final_prompt = (
        prompt
        .replace(
            "{analysis}",
            json.dumps(
                state["analysis"],
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{test_scope}",
            json.dumps(
                state["test_scope"],
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt
    )

    content = (
        response.content
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:

        scenarios = json.loads(
            content
        )

        save_scenarios(
            state["ticket_id"],
            scenarios
        )

    except Exception:

        scenarios = [
            {
                "raw_response": content
            }
        ]

    return {
        "scenarios": scenarios
    }