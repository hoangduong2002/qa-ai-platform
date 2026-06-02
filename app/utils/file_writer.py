import json
from pathlib import Path
from typing import Any


def save_json(
    file_path: Path,
    data: Any
):

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return str(file_path)


def save_analysis(
    ticket_id: str,
    analysis: dict
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "analysis"
        / "requirement_analysis.json",
        analysis
    )


def save_requirement_items(
    ticket_id: str,
    requirement_items: list
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "analysis"
        / "requirement_items.json",
        requirement_items
    )


def save_clarifications(
    ticket_id: str,
    clarifications: dict
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "analysis"
        / "clarifications.json",
        clarifications
    )


def save_test_scope(
    ticket_id: str,
    test_scope: dict
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "analysis"
        / "test_scope.json",
        test_scope
    )


def save_scenarios(
    ticket_id: str,
    scenarios: list
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "scenarios"
        / "scenarios.json",
        scenarios
    )


def save_testcases(
    ticket_id: str,
    testcases: list
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "testcases"
        / "testcases.json",
        testcases
    )


def save_improved_testcases(
    ticket_id: str,
    testcases: list,
    version: str = "latest"
):

    latest_file = (
        Path("requirements")
        / ticket_id
        / "testcases"
        / "improved_testcases.json"
    )

    save_json(
        latest_file,
        testcases
    )

    if version != "latest":
        return save_json(
            Path("requirements")
            / ticket_id
            / "testcases"
            / f"improved_testcases_{version}.json",
            testcases
        )

    return str(latest_file)


def save_coverage_review(
    ticket_id: str,
    review: dict
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "review"
        / "coverage_review.json",
        review
    )


def save_final_coverage_review(
    ticket_id: str,
    review: dict
):

    return save_json(
        Path("requirements")
        / ticket_id
        / "review"
        / "final_coverage_review.json",
        review
    )


def save_raw_response(
    ticket_id: str,
    step_name: str,
    content: str
):

    output_file = (
        Path("requirements")
        / ticket_id
        / "logs"
        / f"{step_name}.txt"
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        content,
        encoding="utf-8"
    )

    return str(output_file)