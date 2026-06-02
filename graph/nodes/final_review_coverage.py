import json

from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt
from app.utils.llm_json import parse_json
from app.utils.file_writer import (
    save_final_coverage_review
)


def final_review_coverage(state):

    llm = get_llm()

    prompt = load_prompt(
        "prompts/final_review_coverage.md"
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
            "{scenarios}",
            json.dumps(
                state.get("scenarios", []),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{improved_testcases}",
            json.dumps(
                state.get(
                    "improved_testcases",
                    []
                ),
                indent=2,
                ensure_ascii=False
            )
        )
        .replace(
            "{coverage_review}",
            json.dumps(
                state.get(
                    "coverage_review",
                    {}
                ),
                indent=2,
                ensure_ascii=False
            )
        )
    )

    response = llm.invoke(
        final_prompt
    )

    try:

        final_review = parse_json(
            response.content
        )

        save_final_coverage_review(
            state["ticket_id"],
            final_review
        )

    except Exception:

        final_review = {
            "raw_response":
            response.content
        }

    return {
        "final_coverage_review":
        final_review
    }