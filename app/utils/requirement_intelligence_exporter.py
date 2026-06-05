from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


def _apply_styles(wb: Workbook):

    header_fill = PatternFill(
        "solid",
        fgColor="D9EAF7"
    )

    border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin")
    )

    for sheet in wb.worksheets:

        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(
                vertical="center",
                wrap_text=True
            )
            cell.border = border

        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True
                )
                cell.border = border

        for column_cells in sheet.columns:
            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )

            sheet.column_dimensions[
                column_cells[0].column_letter
            ].width = min(
                max_length + 2,
                70
            )


def export_requirement_intelligence_to_excel(
    ticket_id: str,
    analysis: dict,
    clarifications: dict,
    clarification_answers: dict,
    requirement_summary: dict
):

    output_dir = (
        Path("requirements")
        / ticket_id
        / "exports"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        output_dir
        / "requirement_intelligence.xlsx"
    )

    wb = Workbook()

    # Sheet 1: Requirements
    ws_req = wb.active
    ws_req.title = "Requirements"

    ws_req.append(
        [
            "Requirement ID",
            "Type",
            "Description"
        ]
    )

    for item in analysis.get(
        "requirement_items",
        []
    ):
        ws_req.append(
            [
                item.get("requirement_id", ""),
                item.get("type", ""),
                item.get("description", "")
            ]
        )

    # Sheet 2: Clarifications
    ws_clar = wb.create_sheet(
        "Clarifications"
    )

    ws_clar.append(
        [
            "Question ID",
            "Category",
            "Question",
            "Impact",
            "Reason",
            "Answer",
            "Status",
            "Answered At"
        ]
    )

    questions = clarifications.get(
        "clarification_questions",
        []
    )

    answered_clarifications = (
        clarification_answers.get(
            "answered_clarifications",
            []
        )
    )

    answers_map = {
        item.get("question_id", ""): item
        for item in answered_clarifications
    }

    for question in questions:

        question_id = question.get(
            "question_id",
            ""
        )

        answer_info = answers_map.get(
            question_id,
            {}
        )

        answer = answer_info.get(
            "answer",
            ""
        )

        status = (
            "Answered"
            if answer
            else "Open"
        )

        ws_clar.append(
            [
                question_id,
                question.get("category", ""),
                question.get("question", ""),
                question.get("impact", ""),
                question.get("reason", ""),
                answer,
                status,
                answer_info.get("answered_at", "")
            ]
        )

    # Sheet 3: Requirement Summary
    ws_summary = wb.create_sheet(
        "Requirement Summary"
    )

    ws_summary.append(
        [
            "Section",
            "Content"
        ]
    )

    ws_summary.append(
        [
            "Executive Summary",
            requirement_summary.get(
                "executive_summary",
                ""
            )
        ]
    )

    ws_summary.append(
        [
            "Functional Summary",
            requirement_summary.get(
                "functional_summary",
                ""
            )
        ]
    )

    for key in [
        "confirmed_business_rules",
        "validation_rules",
        "open_questions",
        "assumptions",
        "risks"
    ]:
        value = requirement_summary.get(
            key,
            []
        )

        if isinstance(value, list):
            value = "\n".join(
                str(item)
                for item in value
            )

        ws_summary.append(
            [
                key,
                value
            ]
        )

    _apply_styles(wb)

    wb.save(
        output_file
    )

    return str(
        output_file
    )