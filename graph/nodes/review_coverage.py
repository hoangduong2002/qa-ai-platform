import json

from app.services.llm_service import (
    get_llm
)

from app.utils.prompt_loader import (
    load_prompt
)

from app.utils.file_writer import (
    save_coverage_review
)


def review_coverage(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/review_coverage.md"
    )

    final_prompt = (
        prompt
        .replace(
            "{analysis}",
            json.dumps(
                state["analysis"],
                indent=2
            )
        )
        .replace(
            "{scenarios}",
            json.dumps(
                state["scenarios"],
                indent=2
            )
        )
        .replace(
            "{testcases}",
            json.dumps(
                state["testcases"],
                indent=2
            )
        )
    )

    response = llm.invoke(
        final_prompt
    )

    content = (
        response.content
        .replace(
            "```json",
            ""
        )
        .replace(
            "```",
            ""
        )
        .strip()
    )

    try:

        coverage_review = (
            json.loads(content)
        )

        save_coverage_review(
            state["ticket_id"],
            coverage_review
        )

    except Exception:

        coverage_review = {
            "raw_response":
            content
        }

    return {
        "coverage_review":
        coverage_review
    }