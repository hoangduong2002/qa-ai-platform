import json
from pathlib import Path


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

    scenarios = load_json_file(
        root / "scenarios" / "scenarios.json",
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

    return {
        "ticket_id": ticket_id,
        "analysis": analysis,
        "scenarios": scenarios,
        "testcases": testcases,
        "coverage_review": coverage_review,
        "final_coverage_review": final_coverage_review,
        "session": session
    }