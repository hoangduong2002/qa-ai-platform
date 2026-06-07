import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.utils.test_structure_store import load_approved_test_case_structure


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
BOLD_FONT = Font(bold=True)
THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)


def _safe_sheet_name(name: str) -> str:
    invalid_chars = ["\\", "/", "*", "[", "]", ":", "?"]

    clean_name = name or "Sheet"

    for char in invalid_chars:
        clean_name = clean_name.replace(char, "_")

    clean_name = clean_name.strip()

    if not clean_name:
        clean_name = "Sheet"

    return clean_name[:31]


def _to_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "\n".join(_to_text(item) for item in value)

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)

    return str(value)


def _ensure_exports_dir(ticket_id: str) -> Path:
    exports_dir = Path("requirements") / ticket_id / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    return exports_dir


def _apply_table_style(ws, freeze_row: int = 1) -> None:
    ws.freeze_panes = f"A{freeze_row + 1}"
    ws.auto_filter.ref = ws.dimensions

    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )
            cell.border = THIN_BORDER

    for cell in ws[freeze_row]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )


def _auto_width(ws, max_width: int = 60) -> None:
    for column_cells in ws.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = 0

        for cell in column_cells:
            value = cell.value

            if value is None:
                continue

            lines = str(value).splitlines() or [str(value)]

            for line in lines:
                max_length = max(max_length, len(line))

        ws.column_dimensions[column_letter].width = min(
            max(max_length + 2, 12),
            max_width,
        )


def _append_kv(ws, key: str, value: Any) -> None:
    row = ws.max_row + 1
    ws.cell(row=row, column=1, value=key)
    ws.cell(row=row, column=2, value=_to_text(value))
    ws.cell(row=row, column=1).font = BOLD_FONT
    ws.cell(row=row, column=1).fill = SECTION_FILL


def _get_functions(approved_structure: dict) -> list[dict]:
    if not isinstance(approved_structure, dict):
        return []

    functions = (
        approved_structure.get("main_functions")
        or approved_structure.get("functions")
        or approved_structure.get("test_functions")
        or []
    )

    if not isinstance(functions, list):
        return []

    return functions


def _get_function_id(function_item: dict) -> str:
    if not isinstance(function_item, dict):
        return ""

    return (
        function_item.get("function_id")
        or function_item.get("main_function_id")
        or function_item.get("id")
        or ""
    )


def _get_function_name(function_item: dict) -> str:
    if not isinstance(function_item, dict):
        return ""

    return (
        function_item.get("name")
        or function_item.get("title")
        or function_item.get("function_name")
        or ""
    )


def _get_item_function_id(item: dict) -> str:
    if not isinstance(item, dict):
        return ""

    return (
        item.get("function_id")
        or item.get("main_function_id")
        or ""
    )


def _group_testcases_by_function(
    testcases: list,
    approved_structure: dict,
) -> dict[str, dict]:
    groups = {}

    for function_item in _get_functions(approved_structure):
        function_id = _get_function_id(function_item)

        if not function_id:
            continue

        groups[function_id] = {
            "function": function_item,
            "testcases": [],
        }

    for testcase in testcases:
        if not isinstance(testcase, dict):
            continue

        function_id = _get_item_function_id(testcase)

        if function_id not in groups:
            function_id = "UNMAPPED"

            if function_id not in groups:
                groups[function_id] = {
                    "function": {
                        "function_id": "UNMAPPED",
                        "name": "Unmapped Test Cases",
                    },
                    "testcases": [],
                }

        groups[function_id]["testcases"].append(testcase)

    return groups


def _write_testcase_header(ws) -> None:
    headers = [
        "Test Case ID",
        "Scenario ID",
        "Function ID",
        "Sub Function ID",
        "Test Area ID",
        "Title",
        "Type",
        "Priority",
        "Preconditions",
        "Test Steps",
        "Expected Results",
        "Test Data",
        "Related Requirement IDs",
        "Traceability",
    ]

    ws.append(headers)


def _write_testcase_row(ws, testcase: dict) -> None:
    ws.append(
        [
            testcase.get("testcase_id", ""),
            testcase.get("scenario_id", ""),
            testcase.get("function_id", ""),
            testcase.get("sub_function_id", ""),
            testcase.get("test_area_id", ""),
            testcase.get("title", ""),
            testcase.get("type", ""),
            testcase.get("priority", ""),
            _to_text(testcase.get("preconditions", [])),
            _to_text(testcase.get("test_steps", [])),
            _to_text(testcase.get("expected_results", [])),
            _to_text(testcase.get("test_data", {})),
            _to_text(testcase.get("related_requirement_ids", [])),
            testcase.get("traceability", ""),
        ]
    )


def _create_summary_sheet(
    wb: Workbook,
    ticket_id: str,
    approved_structure: dict,
    testcases: list,
    coverage_review: dict,
    final_coverage_review: dict,
) -> None:
    ws = wb.active
    ws.title = "Summary"

    ws.append(["Field", "Value"])

    _append_kv(ws, "Requirement ID", ticket_id)
    _append_kv(ws, "Generation Mode", "Function-Based Structured Generation")
    _append_kv(ws, "Main Functions", len(_get_functions(approved_structure)))
    _append_kv(ws, "Total Test Cases", len(testcases))
    _append_kv(ws, "Coverage Score", coverage_review.get("coverage_score", ""))
    _append_kv(ws, "Coverage Approved By AI", coverage_review.get("approved_by_ai", ""))
    _append_kv(
        ws,
        "Final Coverage Score",
        final_coverage_review.get("final_coverage_score")
        or final_coverage_review.get("coverage_score")
        or "",
    )
    _append_kv(
        ws,
        "Ready For Execution",
        final_coverage_review.get("ready_for_execution", ""),
    )
    _append_kv(
        ws,
        "Final Approved By AI",
        final_coverage_review.get("approved_by_ai", ""),
    )

    _apply_table_style(ws)
    _auto_width(ws)


def _create_master_testcases_sheet(wb: Workbook, testcases: list) -> None:
    ws = wb.create_sheet("Master Test Cases")
    _write_testcase_header(ws)

    for testcase in testcases:
        _write_testcase_row(ws, testcase)

    _apply_table_style(ws)
    _auto_width(ws)


def _create_function_testcase_sheets(
    wb: Workbook,
    grouped_testcases: dict[str, dict],
) -> None:
    for function_id, group in grouped_testcases.items():
        function_item = group["function"]
        function_name = _get_function_name(function_item)

        sheet_name = _safe_sheet_name(function_id)

        ws = wb.create_sheet(sheet_name)

        ws.append(["Function ID", function_id])
        ws.append(["Function Name", function_name])
        ws.append([])
        _write_testcase_header(ws)

        for testcase in group["testcases"]:
            _write_testcase_row(ws, testcase)

        _apply_table_style(ws, freeze_row=4)
        _auto_width(ws)


def _create_coverage_review_sheet(
    wb: Workbook,
    coverage_review: dict,
) -> None:
    ws = wb.create_sheet("Coverage Review")

    ws.append(
        [
            "Function ID",
            "Function Name",
            "Coverage Score",
            "Approved By AI",
            "Scenario Count",
            "Test Case Count",
            "Summary",
            "Missing Scenarios",
            "Weak Test Cases",
            "Missing Test Cases",
            "Traceability Issues",
            "Recommendations",
        ]
    )

    function_reviews = coverage_review.get("function_reviews", [])

    if function_reviews:
        for review in function_reviews:
            ws.append(
                [
                    review.get("function_id", ""),
                    review.get("function_name", ""),
                    review.get("coverage_score", ""),
                    review.get("approved_by_ai", ""),
                    review.get("scenario_count", ""),
                    review.get("testcase_count", ""),
                    review.get("summary", ""),
                    _to_text(review.get("missing_scenarios", [])),
                    _to_text(review.get("weak_testcases", [])),
                    _to_text(review.get("missing_testcases", [])),
                    _to_text(review.get("traceability_issues", [])),
                    _to_text(review.get("recommendations", [])),
                ]
            )
    else:
        ws.append(
            [
                "",
                "",
                coverage_review.get("coverage_score", ""),
                coverage_review.get("approved_by_ai", ""),
                coverage_review.get("scenario_count", ""),
                coverage_review.get("testcase_count", ""),
                coverage_review.get("summary", ""),
                _to_text(coverage_review.get("missing_scenarios", [])),
                _to_text(coverage_review.get("weak_testcases", [])),
                _to_text(coverage_review.get("missing_testcases", [])),
                _to_text(coverage_review.get("traceability_issues", [])),
                _to_text(coverage_review.get("recommendations", [])),
            ]
        )

    _apply_table_style(ws)
    _auto_width(ws)


def _create_final_review_sheet(
    wb: Workbook,
    final_coverage_review: dict,
) -> None:
    ws = wb.create_sheet("Final Review")

    ws.append(
        [
            "Function ID",
            "Function Name",
            "Final Coverage Score",
            "Approved By AI",
            "Ready For Execution",
            "Scenario Count",
            "Test Case Count",
            "Summary",
            "Remaining Gaps",
            "Traceability Issues",
            "Execution Readiness Issues",
            "Final Recommendations",
        ]
    )

    function_reviews = final_coverage_review.get("function_reviews", [])

    if function_reviews:
        for review in function_reviews:
            ws.append(
                [
                    review.get("function_id", ""),
                    review.get("function_name", ""),
                    review.get("final_coverage_score", ""),
                    review.get("approved_by_ai", ""),
                    review.get("ready_for_execution", ""),
                    review.get("scenario_count", ""),
                    review.get("testcase_count", ""),
                    review.get("summary", ""),
                    _to_text(review.get("remaining_gaps", [])),
                    _to_text(review.get("traceability_issues", [])),
                    _to_text(review.get("execution_readiness_issues", [])),
                    _to_text(review.get("final_recommendations", [])),
                ]
            )
    else:
        ws.append(
            [
                "",
                "",
                final_coverage_review.get("final_coverage_score")
                or final_coverage_review.get("coverage_score", ""),
                final_coverage_review.get("approved_by_ai", ""),
                final_coverage_review.get("ready_for_execution", ""),
                final_coverage_review.get("scenario_count", ""),
                final_coverage_review.get("testcase_count", ""),
                final_coverage_review.get("summary", ""),
                _to_text(final_coverage_review.get("remaining_gaps", [])),
                _to_text(final_coverage_review.get("traceability_issues", [])),
                _to_text(final_coverage_review.get("execution_readiness_issues", [])),
                _to_text(final_coverage_review.get("final_recommendations", [])),
            ]
        )

    _apply_table_style(ws)
    _auto_width(ws)


def _create_traceability_matrix_sheet(
    wb: Workbook,
    testcases: list,
) -> None:
    ws = wb.create_sheet("Traceability Matrix")

    ws.append(
        [
            "Requirement ID",
            "Function ID",
            "Scenario ID",
            "Test Case ID",
            "Test Case Title",
            "Priority",
            "Type",
        ]
    )

    for testcase in testcases:
        requirement_ids = testcase.get("related_requirement_ids", [])

        if isinstance(requirement_ids, str):
            requirement_ids = [
                item.strip()
                for item in requirement_ids.split(",")
                if item.strip()
            ]

        if not isinstance(requirement_ids, list):
            requirement_ids = []

        for requirement_id in requirement_ids:
            ws.append(
                [
                    requirement_id,
                    testcase.get("function_id", ""),
                    testcase.get("scenario_id", ""),
                    testcase.get("testcase_id", ""),
                    testcase.get("title", ""),
                    testcase.get("priority", ""),
                    testcase.get("type", ""),
                ]
            )

    _apply_table_style(ws)
    _auto_width(ws)


def export_function_based_testcases_to_excel(
    ticket_id: str,
    testcases: list,
    coverage_review: dict | None = None,
    final_coverage_review: dict | None = None,
    approved_structure: dict | None = None,
) -> str:
    coverage_review = coverage_review or {}
    final_coverage_review = final_coverage_review or {}

    if approved_structure is None:
        approved_structure = load_approved_test_case_structure(ticket_id)

    wb = Workbook()

    grouped_testcases = _group_testcases_by_function(
        testcases=testcases,
        approved_structure=approved_structure or {},
    )

    _create_summary_sheet(
        wb=wb,
        ticket_id=ticket_id,
        approved_structure=approved_structure or {},
        testcases=testcases,
        coverage_review=coverage_review,
        final_coverage_review=final_coverage_review,
    )

    _create_master_testcases_sheet(
        wb=wb,
        testcases=testcases,
    )

    _create_function_testcase_sheets(
        wb=wb,
        grouped_testcases=grouped_testcases,
    )

    _create_coverage_review_sheet(
        wb=wb,
        coverage_review=coverage_review,
    )

    _create_final_review_sheet(
        wb=wb,
        final_coverage_review=final_coverage_review,
    )

    _create_traceability_matrix_sheet(
        wb=wb,
        testcases=testcases,
    )

    exports_dir = _ensure_exports_dir(ticket_id)
    export_file = exports_dir / f"{ticket_id}_function_based_testcases.xlsx"

    wb.save(export_file)

    return str(export_file)