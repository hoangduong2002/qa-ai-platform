import json
from pathlib import Path
from app.utils.review_comment_session import (
    load_review_comments
)
from app.utils.review_comment_session import (
    load_review_comments
)
from app.utils.improvement_history import (
    load_improvement_history
)

def enrich_analysis_with_review_comments(
    analysis: dict,
    review_comments: list
) -> dict:

    analysis = analysis or {}

    requirement_items = list(
        analysis.get(
            "requirement_items",
            []
        )
    )

    existing_ids = {
        item.get("requirement_id")
        for item in requirement_items
    }

    for comment in review_comments:

        comment_id = comment.get(
            "comment_id",
            ""
        )

        if not comment_id:
            continue

        if comment_id in existing_ids:
            continue

        requirement_items.append(
            {
                "requirement_id": comment_id,
                "type": "Review Comment",
                "description": comment.get(
                    "comment",
                    ""
                )
            }
        )

    analysis["requirement_items"] = requirement_items

    return analysis


def load_json_file(file_path: Path, default):
    if not file_path.exists():
        return default

    return json.loads(
        file_path.read_text(
            encoding="utf-8"
        )
    )


def load_ticket_artifacts(ticket_id: str):
    root = Path("requirements") / ticket_id

    analysis = load_json_file(
        root / "analysis" / "requirement_analysis.json",
        {}
    )
    
    clarifications = load_json_file(
        root / "analysis" / "clarification_questions_snapshot.json",
        {}
    )

    if not clarifications:
        clarifications = load_json_file(
            root / "analysis" / "clarifications.json",
            {}
        )
    
    clarification_answers = load_json_file(
        root / "analysis" / "clarification_answers.json",
        {}
    )
    
    review_comments = load_review_comments(
        ticket_id
    )
    
    analysis = enrich_analysis_with_review_comments(
        analysis,
        review_comments
    )
    
    requirement_qa = load_json_file(
        root / "analysis" / "requirement_qa.json",
        {}
    )

    requirement_summary = load_json_file(
        root / "analysis" / "requirement_summary.json",
        {}
    )
    
    test_scope = load_json_file(
        root / "analysis" / "test_scope.json",
        {}
    )    

    scenarios = load_json_file(
        root / "analysis" / "scenarios.json",
        []
    )

    testcases = load_json_file(
        root / "testcases" / "improved_testcases.json",
        []
    )

    if not testcases:
        testcases = load_json_file(
            root / "testcases" / "testcases.json",
            []
        )

    coverage_review = load_json_file(
        root / "review" / "coverage_review.json",
        {}
    )

    final_coverage_review = load_json_file(
        root / "review" / "final_coverage_review.json",
        {}
    )

    session = load_json_file(
        root / "review" / "review_session.json",
        {
            "improve_iterations": 0,
            "max_iterations": 3,
            "accepted": False
        }
    )
    
    improvement_history = load_improvement_history(ticket_id)

    return {
        "ticket_id": ticket_id,
        "analysis": analysis,
        "requirement_qa": requirement_qa,
        "clarifications": clarifications,
        "clarification_answers": clarification_answers,
        "requirement_summary": requirement_summary,
        "review_comments": review_comments,
        "test_scope": test_scope,
        "scenarios": scenarios,
        "testcases": testcases,
        "coverage_review": coverage_review,
        "final_coverage_review": final_coverage_review,
        "improvement_history": improvement_history,
        "session": session
    }