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
            "{requirement_summary}",
            json.dumps(
                state.get(
                    "requirement_summary",
                    {}
                ),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{testcases}",
            json.dumps(
                state.get(
                    "testcases",
                    []
                ),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt,
        ticket_id=state.get("ticket_id", ""),
        node_name="review_coverage"
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