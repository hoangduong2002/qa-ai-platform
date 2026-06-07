import shutil
from pathlib import Path

from app.exporters.function_based_excel_exporter import (
    export_function_based_testcases_to_excel,
)
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.improvement_history import save_improvement_history_item


def _versioned_excel_path(
    ticket_id: str,
    base_excel_file: str,
    version: str,
) -> str:
    source_path = Path(base_excel_file)

    if not version:
        return str(source_path)

    if version == "latest":
        return str(source_path)

    versioned_path = (
        source_path.parent
        / f"{ticket_id}_function_based_testcases_{version}.xlsx"
    )

    shutil.copyfile(source_path, versioned_path)

    return str(versioned_path)


def export_generation_result_to_excel(
    ticket_id: str,
    result: dict,
    version: str = "latest",
) -> str:
    artifacts = load_ticket_artifacts(ticket_id)

    testcases = (
        result.get("improved_testcases")
        or result.get("testcases")
        or artifacts.get("improved_testcases")
        or artifacts.get("testcases")
        or []
    )

    coverage_review = (
        result.get("coverage_review")
        or artifacts.get("coverage_review")
        or {}
    )

    final_coverage_review = (
        result.get("final_coverage_review")
        or artifacts.get("final_coverage_review")
        or {}
    )

    approved_structure = (
        result.get("approved_test_case_structure")
        or artifacts.get("approved_test_case_structure")
        or {}
    )

    excel_file = export_function_based_testcases_to_excel(
        ticket_id=ticket_id,
        testcases=testcases,
        coverage_review=coverage_review,
        final_coverage_review=final_coverage_review,
        approved_structure=approved_structure,
    )

    return _versioned_excel_path(
        ticket_id=ticket_id,
        base_excel_file=excel_file,
        version=version,
    )


def save_generation_history(
    ticket_id: str,
    result: dict,
    version: str,
    iteration: int,
    note: str,
) -> None:
    final_review = result.get("final_coverage_review", {})

    save_improvement_history_item(
        ticket_id=ticket_id,
        version=version,
        iteration=iteration,
        coverage_score=(
            final_review.get("final_coverage_score")
            or final_review.get("coverage_score")
            or ""
        ),
        improvement_score=final_review.get("improvement_score", ""),
        note=note,
    )