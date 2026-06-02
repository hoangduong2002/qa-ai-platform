import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.testcase_writer import save_testcases
from app.utils.llm_json import parse_json


def generate_testcases(state):
    
    llm = get_llm()

    prompt = load_prompt(
        "prompts/generate_testcases.md"
    )

    final_prompt = prompt.replace(
        "{scenarios}",
        json.dumps(
            state["scenarios"],
            indent=2
        )
    )

    response = llm.invoke(
        final_prompt
    )

    try:

        testcases = parse_json(
            response.content
        )

        save_testcases(
            state["ticket_id"],
            testcases
        )

    except Exception:

        testcases = [
            {
                "raw_response":
                response.content
            }
        ]

    return {
        "testcases": testcases
    }