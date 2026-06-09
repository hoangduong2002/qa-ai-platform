import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile

from app.services.jira_requirement_service import (
    create_requirement_from_jira,
)

from app.services.requirement_sanitization_service import (
    sanitize_requirement_for_analysis,
)

from graph.nodes.load_requirement import (
    load_requirement,
)

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


REQUIREMENTS_DIR = Path("requirements")

def _read_json(
    file_path: Path,
):
    if not file_path.exists():
        return None

    try:
        return json.loads(
            file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        )
    except Exception:
        return None

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_requirement_id(value: str) -> str:
    value = value.strip().replace(" ", "-")
    safe = []

    for char in value:
        if char.isalnum() or char in ["-", "_"]:
            safe.append(char)

    result = "".join(safe).upper()

    if not result:
        raise ValueError("Requirement name is invalid.")

    return result


def _requirement_dir(ticket_id: str) -> Path:
    return REQUIREMENTS_DIR / ticket_id


def _source_dir(ticket_id: str) -> Path:
    return _requirement_dir(ticket_id) / "source"


def _analysis_dir(ticket_id: str) -> Path:
    return _requirement_dir(ticket_id) / "analysis"


def _ticket_json_file(ticket_id: str) -> Path:
    return _requirement_dir(ticket_id) / "ticket.json"


def list_requirements() -> list[dict]:
    if not REQUIREMENTS_DIR.exists():
        return []

    items = []

    for path in REQUIREMENTS_DIR.iterdir():
        if not path.is_dir():
            continue

        if path.name.startswith("_"):
            continue

        ticket_file = path / "ticket.json"

        if ticket_file.exists():
            try:
                data = json.loads(
                    ticket_file.read_text(encoding="utf-8")
                )
            except Exception:
                data = {}
        else:
            data = {}

        items.append(
            {
                "ticket_id": path.name,
                "summary": data.get("summary", path.name),
                "source": data.get("source", "unknown"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "has_analysis": (path / "analysis" / "requirement_analysis.json").exists(),
                "has_sanitized": (path / "analysis" / "sanitized_requirement.md").exists(),
            }
        )

    return sorted(
        items,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )


async def create_manual_requirement(
    requirement_name: str,
    description: str,
    files: Optional[List[UploadFile]] = None,
) -> str:
    ticket_id = _safe_requirement_id(requirement_name)

    base_dir = _requirement_dir(ticket_id)

    if base_dir.exists():
        raise ValueError(f"Requirement already exists: {ticket_id}")

    source_dir = _source_dir(ticket_id)
    uploads_dir = source_dir / "uploads"
    extracted_dir = source_dir / "extracted"
    analysis_dir = _analysis_dir(ticket_id)

    source_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    description_file = source_dir / "description.md"
    comments_file = source_dir / "comments.md"

    description_file.write_text(
        description.strip(),
        encoding="utf-8",
    )

    comments_file.write_text(
        "",
        encoding="utf-8",
    )

    uploaded_content_parts = []

    if files:
        for upload_file in files:
            if not upload_file.filename:
                continue

            saved_file = uploads_dir / upload_file.filename

            content = await upload_file.read()

            saved_file.write_bytes(content)

            extracted_text = extract_file_text(saved_file)

            extracted_file = extracted_dir / f"{saved_file.stem}.txt"

            extracted_file.write_text(
                extracted_text,
                encoding="utf-8",
            )

            if extracted_text.strip():
                uploaded_content_parts.append(
                    f"## File: {upload_file.filename}\n\n{extracted_text}"
                )

    uploaded_content = "\n\n".join(uploaded_content_parts)

    if uploaded_content:
        uploaded_content_file = source_dir / "uploaded_content.md"
        uploaded_content_file.write_text(
            uploaded_content,
            encoding="utf-8",
        )

    ticket_data = {
        "ticket_id": ticket_id,
        "summary": requirement_name.strip(),
        "source": "web_manual",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    _ticket_json_file(ticket_id).write_text(
        json.dumps(ticket_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    sanitize_existing_requirement(ticket_id)

    return ticket_id


def create_requirement_from_jira_and_sanitize(
    issue_key: str,
    jira_pat: str = "",
    refresh_existing: bool = False,
) -> str:
    issue_key = issue_key.strip()
    ticket_id = _safe_requirement_id(issue_key)

    if requirement_exists(ticket_id) and not refresh_existing:
        return ticket_id

    ticket_id = create_requirement_from_jira(
        issue_key.strip(),
        jira_pat=jira_pat.strip(),
        refresh_existing=refresh_existing,
    )

    sanitize_existing_requirement(ticket_id)

    return ticket_id


def sanitize_existing_requirement(
    ticket_id: str,
) -> str:
    state = {
        "ticket_id": ticket_id,
    }

    state.update(
        load_requirement(state)
    )

    requirement_context = state.get("requirement_context", "")

    sanitized = sanitize_requirement_for_analysis(
        ticket_id=ticket_id,
        raw_requirement=requirement_context,
    )

    return sanitized


def get_requirement_detail(
    ticket_id: str,
) -> dict:
    base_dir = _requirement_dir(ticket_id)
    source_dir = _source_dir(ticket_id)
    analysis_dir = _analysis_dir(ticket_id)

    ticket_file = _ticket_json_file(ticket_id)
    description_file = source_dir / "description.md"
    comments_file = source_dir / "comments.md"
    uploaded_content_file = source_dir / "uploaded_content.md"
    sanitized_file = analysis_dir / "sanitized_requirement.md"

    requirement_analysis_file = analysis_dir / "requirement_analysis.json"
    requirement_items_file = analysis_dir / "requirement_items.json"
    clarifications_file = analysis_dir / "clarifications.json"
    requirement_summary_file = analysis_dir / "requirement_summary.json"

    if not base_dir.exists():
        raise FileNotFoundError(
            f"Requirement not found: {ticket_id}"
        )

    ticket_data = {}

    if ticket_file.exists():
        ticket_data = json.loads(
            ticket_file.read_text(
                encoding="utf-8",
            )
        )

    requirement_analysis = _read_json(
        requirement_analysis_file
    )

    requirement_items = _read_json(
        requirement_items_file
    )

    clarifications_raw = _read_json(
        clarifications_file
    )

    clarifications = _normalize_clarifications(
        clarifications_raw
    )

    requirement_summary = _read_json(
        requirement_summary_file
    )

    return {
        "ticket_id": ticket_id,
        "ticket": ticket_data,
        "description": _read_text(description_file),
        "comments": _read_text(comments_file),
        "uploaded_content": _read_text(uploaded_content_file),
        "sanitized_requirement": _read_text(sanitized_file),

        "requirement_analysis": requirement_analysis,
        "requirement_items": requirement_items,
        "clarifications": clarifications,
        "requirement_summary": requirement_summary,

        "has_sanitized": sanitized_file.exists(),
        "has_analysis": requirement_analysis_file.exists(),
        "has_items": requirement_items_file.exists(),
        "has_summary": requirement_summary_file.exists(),
        "has_clarifications": len(clarifications) > 0,
    }


def update_requirement(
    ticket_id: str,
    summary: str,
    description: str,
    comments: str = "",
) -> None:
    base_dir = _requirement_dir(ticket_id)
    source_dir = _source_dir(ticket_id)

    if not base_dir.exists():
        raise FileNotFoundError(f"Requirement not found: {ticket_id}")

    (source_dir / "description.md").write_text(
        description.strip(),
        encoding="utf-8",
    )

    (source_dir / "comments.md").write_text(
        comments.strip(),
        encoding="utf-8",
    )

    ticket_file = _ticket_json_file(ticket_id)

    ticket_data = {}
    if ticket_file.exists():
        ticket_data = json.loads(
            ticket_file.read_text(encoding="utf-8")
        )

    ticket_data["summary"] = summary.strip()
    ticket_data["updated_at"] = _now_iso()

    ticket_file.write_text(
        json.dumps(ticket_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    sanitize_existing_requirement(ticket_id)


def delete_requirement(
    ticket_id: str,
) -> None:
    base_dir = _requirement_dir(ticket_id)

    if not base_dir.exists():
        raise FileNotFoundError(f"Requirement not found: {ticket_id}")

    deleted_dir = REQUIREMENTS_DIR / "_deleted"
    deleted_dir.mkdir(parents=True, exist_ok=True)

    target_dir = deleted_dir / f"{ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    shutil.move(
        str(base_dir),
        str(target_dir),
    )


def extract_file_text(
    file_path: Path,
) -> str:
    suffix = file_path.suffix.lower()

    if suffix in [".txt", ".md", ".csv", ".json", ".xml", ".log"]:
        return file_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    if suffix == ".docx":
        return _extract_docx(file_path)

    if suffix == ".pptx":
        return _extract_pptx(file_path)

    return f"[Unsupported file type for text extraction: {file_path.name}]"


def _extract_docx(
    file_path: Path,
) -> str:
    try:
        from docx import Document
    except ImportError:
        return "[python-docx is not installed. Run: pip install python-docx]"

    document = Document(str(file_path))

    paragraphs = [
        paragraph.text
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ]

    return "\n".join(paragraphs)


def _extract_pptx(
    file_path: Path,
) -> str:
    try:
        from pptx import Presentation
    except ImportError:
        return "[python-pptx is not installed. Run: pip install python-pptx]"

    presentation = Presentation(str(file_path))

    texts = []

    for slide_index, slide in enumerate(presentation.slides, start=1):
        texts.append(f"# Slide {slide_index}")

        for shape in slide.shapes:
            if hasattr(shape, "text"):
                value = shape.text.strip()
                if value:
                    texts.append(value)

    return "\n\n".join(texts)


def _read_text(
    file_path: Path,
) -> str:
    if not file_path.exists():
        return ""

    return file_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )
    

def get_clarification_questions(
    ticket_id: str,
) -> list[dict]:
    analysis_dir = _analysis_dir(ticket_id)

    clarification_file = (
        analysis_dir / "clarifications.json"
    )

    data = _read_json(
        clarification_file
    )

    if not data:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("clarification_questions"), list):
            return data["clarification_questions"]

        if isinstance(data.get("questions"), list):
            return data["questions"]

        if isinstance(data.get("clarifications"), list):
            return data["clarifications"]

    return []


def save_clarification_answers(
    ticket_id: str,
    answers: dict,
) -> None:
    base_dir = _requirement_dir(ticket_id)
    source_dir = _source_dir(ticket_id)
    analysis_dir = _analysis_dir(ticket_id)

    if not base_dir.exists():
        raise FileNotFoundError(
            f"Requirement not found: {ticket_id}"
        )

    analysis_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    questions = get_clarification_questions(
        ticket_id
    )

    answer_items = []

    for question in questions:
        question_id = (
            question.get("question_id")
            or question.get("id")
            or ""
        )

        answer_text = answers.get(
            question_id,
            ""
        ).strip()

        answer_items.append(
            {
                "question_id": question_id,
                "question": question.get("question", ""),
                "impact": question.get("impact", ""),
                "answer": answer_text,
            }
        )

    answers_file = (
        analysis_dir / "clarification_answers.json"
    )

    answers_file.write_text(
        json.dumps(
            answer_items,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    notes = _build_clarification_answer_notes(
        answer_items
    )

    notes_file = (
        source_dir / "clarification_answer_notes.md"
    )

    notes_file.write_text(
        notes,
        encoding="utf-8",
    )


def _build_clarification_answer_notes(
    answer_items: list[dict],
) -> str:
    lines = [
        "# Clarification Answer Notes",
        "",
        "The following answers were provided by the user and must be treated as additional requirement context.",
        "",
    ]

    for item in answer_items:
        answer = item.get("answer", "").strip()

        if not answer:
            continue

        lines.extend(
            [
                f"## {item.get('question_id', '')}",
                "",
                f"Question: {item.get('question', '')}",
                "",
                f"Impact: {item.get('impact', 'N/A')}",
                "",
                f"Answer: {answer}",
                "",
            ]
        )

    return "\n".join(lines).strip()


def export_requirement_summary_to_excel(
    ticket_id: str,
) -> Path:
    analysis_dir = _analysis_dir(ticket_id)

    summary_file = analysis_dir / "requirement_summary.json"

    if not summary_file.exists():
        raise FileNotFoundError(
            f"Requirement summary not found for {ticket_id}"
        )

    requirement_summary = _read_json(summary_file) or {}

    export_dir = analysis_dir / "exports"
    export_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = export_dir / f"{ticket_id}_requirement_summary.xlsx"

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Requirement Summary"

    headers = [
        "Section",
        "ID",
        "Description",
        "Priority",
    ]

    worksheet.append(headers)

    header_fill = PatternFill(
        start_color="1F2937",
        end_color="1F2937",
        fill_type="solid",
    )

    header_font = Font(
        color="FFFFFF",
        bold=True,
    )

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            vertical="center",
            horizontal="center",
        )

    def append_items(
        section_name: str,
        items,
    ):
        if not items:
            return

        if isinstance(items, str):
            worksheet.append(
                [
                    section_name,
                    "",
                    items,
                    "",
                ]
            )
            return

        if isinstance(items, dict):
            worksheet.append(
                [
                    section_name,
                    items.get("id", ""),
                    (
                        items.get("description")
                        or items.get("text")
                        or items.get("requirement")
                        or str(items)
                    ),
                    items.get("priority", ""),
                ]
            )
            return

        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    worksheet.append(
                        [
                            section_name,
                            item.get("id", ""),
                            (
                                item.get("description")
                                or item.get("text")
                                or item.get("requirement")
                                or item.get("rule")
                                or item.get("validation")
                                or item.get("integration")
                                or item.get("error")
                                or str(item)
                            ),
                            item.get("priority", ""),
                        ]
                    )
                else:
                    worksheet.append(
                        [
                            section_name,
                            "",
                            str(item),
                            "",
                        ]
                    )

    overview = requirement_summary.get("overview")

    if overview:
        append_items(
            "Overview",
            overview,
        )

    append_items(
        "Functional Requirements",
        requirement_summary.get("functional_requirements"),
    )

    append_items(
        "Business Rules",
        requirement_summary.get("business_rules"),
    )

    append_items(
        "Validations",
        requirement_summary.get("validations"),
    )

    append_items(
        "Integrations",
        requirement_summary.get("integrations"),
    )

    append_items(
        "Error Handling",
        requirement_summary.get("error_handling"),
    )

    append_items(
        "Non-functional Requirements",
        requirement_summary.get("non_functional_requirements"),
    )

    append_items(
        "Assumptions",
        requirement_summary.get("assumptions"),
    )

    append_items(
        "Out of Scope",
        requirement_summary.get("out_of_scope"),
    )

    append_items(
        "Open Questions",
        requirement_summary.get("open_questions"),
    )

    column_widths = {
        "A": 28,
        "B": 16,
        "C": 100,
        "D": 16,
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[column].width = width

    for row in worksheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    worksheet.freeze_panes = "A2"

    workbook.save(output_file)

    return output_file

def export_requirement_analysis_to_excel(
    ticket_id: str,
) -> Path:
    analysis_dir = _analysis_dir(ticket_id)
    source_dir = _source_dir(ticket_id)

    requirement_analysis_file = analysis_dir / "requirement_analysis.json"
    requirement_items_file = analysis_dir / "requirement_items.json"
    clarifications_file = analysis_dir / "clarifications.json"
    requirement_summary_file = analysis_dir / "requirement_summary.json"
    sanitized_requirement_file = analysis_dir / "sanitized_requirement.md"

    if not requirement_analysis_file.exists():
        raise FileNotFoundError(
            f"Requirement analysis not found for {ticket_id}"
        )

    requirement_analysis = _read_json(requirement_analysis_file) or {}
    requirement_items = _read_json(requirement_items_file) or []
    clarifications_raw = _read_json(
        clarifications_file
    )

    clarifications = _normalize_clarifications(
        clarifications_raw
    )
    requirement_summary = _read_json(requirement_summary_file) or {}
    sanitized_requirement = _read_text(sanitized_requirement_file)

    if not sanitized_requirement:
        sanitized_requirement = _read_text(source_dir / "description.md")

    export_dir = analysis_dir / "exports"
    export_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = export_dir / f"{ticket_id}_analysis_result.xlsx"

    workbook = Workbook()

    default_sheet = workbook.active
    workbook.remove(default_sheet)

    header_fill = PatternFill(
        start_color="1F2937",
        end_color="1F2937",
        fill_type="solid",
    )

    header_font = Font(
        color="FFFFFF",
        bold=True,
    )

    title_font = Font(
        bold=True,
        size=14,
    )

    def style_header_row(worksheet, row_number: int = 1):
        for cell in worksheet[row_number]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(
                vertical="center",
                horizontal="center",
                wrap_text=True,
            )

    def auto_format(worksheet):
        for row in worksheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )

        for column_cells in worksheet.columns:
            max_length = 0
            column_letter = get_column_letter(column_cells[0].column)

            for cell in column_cells:
                value = cell.value
                if value is None:
                    continue

                max_length = max(
                    max_length,
                    min(len(str(value)), 80),
                )

            worksheet.column_dimensions[column_letter].width = max(
                min(max_length + 2, 60),
                14,
            )

        worksheet.freeze_panes = "A2"

    def append_key_value_sheet(
        sheet_name: str,
        data: dict,
    ):
        worksheet = workbook.create_sheet(sheet_name)

        worksheet.append(
            [
                "Section",
                "Value",
            ]
        )
        style_header_row(worksheet)

        for key, value in data.items():
            if isinstance(value, list):
                value_text = "\n".join(
                    [
                        str(item)
                        for item in value
                    ]
                )
            elif isinstance(value, dict):
                value_text = json.dumps(
                    value,
                    indent=2,
                    ensure_ascii=False,
                )
            else:
                value_text = str(value)

            worksheet.append(
                [
                    key,
                    value_text,
                ]
            )

        auto_format(worksheet)

    def append_items_sheet(
        sheet_name: str,
        items,
        headers: list[str],
        row_builder,
    ):
        worksheet = workbook.create_sheet(sheet_name)

        worksheet.append(headers)
        style_header_row(worksheet)

        if isinstance(items, dict):
            possible_items = (
                items.get("items")
                or items.get("requirements")
                or items.get("clarifications")
                or items.get("questions")
                or []
            )
        else:
            possible_items = items

        if not possible_items:
            worksheet.append(
                [
                    "No data",
                ]
            )
        else:
            for index, item in enumerate(possible_items, start=1):
                worksheet.append(
                    row_builder(
                        item,
                        index,
                    )
                )

        auto_format(worksheet)

    def normalize_text_item(item):
        if isinstance(item, dict):
            return (
                item.get("description")
                or item.get("text")
                or item.get("requirement")
                or item.get("rule")
                or item.get("validation")
                or item.get("integration")
                or item.get("error")
                or json.dumps(
                    item,
                    ensure_ascii=False,
                )
            )

        return str(item)

    # Sheet 1: Overview
    overview_sheet = workbook.create_sheet("Overview")
    overview_sheet.append(
        [
            "Field",
            "Value",
        ]
    )
    style_header_row(overview_sheet)

    overview_sheet.append(
        [
            "Ticket ID",
            ticket_id,
        ]
    )

    overview_sheet.append(
        [
            "Requirement Items",
            len(requirement_items)
            if isinstance(requirement_items, list)
            else 0,
        ]
    )

    overview_sheet.append(
        [
            "Clarification Questions",
            len(clarifications)
            if isinstance(clarifications, list)
            else 0,
        ]
    )

    overview_sheet.append(
        [
            "Has Requirement Summary",
            "Yes" if requirement_summary else "No",
        ]
    )

    overview_sheet.append(
        [
            "Export Type",
            "Requirement Analysis Result",
        ]
    )

    auto_format(overview_sheet)

    # Sheet 2: Requirement Analysis
    append_key_value_sheet(
        "Requirement Analysis",
        requirement_analysis,
    )

    # Sheet 3: Requirement Items
    append_items_sheet(
        "Requirement Items",
        requirement_items,
        [
            "ID",
            "Type",
            "Requirement",
            "Priority",
        ],
        lambda item, index: [
            item.get("id")
            or item.get("requirement_id")
            or item.get("item_id")
            or f"REQ-{index:03d}"
            if isinstance(item, dict)
            else f"REQ-{index:03d}",
            item.get("type")
            or item.get("category")
            or item.get("requirement_type")
            or "N/A"
            if isinstance(item, dict)
            else "N/A",
            normalize_text_item(item),
            item.get("priority", "N/A")
            if isinstance(item, dict)
            else "N/A",
        ],
    )

    # Sheet 4: Clarifications
    def build_clarification_row(
        item,
        index: int,
    ):
        if not isinstance(item, dict):
            return [
                f"Q{index:03d}",
                str(item),
                "",
                "",
                "",
                "",
            ]

        question_id = (
            item.get("question_id")
            or item.get("id")
            or item.get("clarification_id")
            or f"Q{index:03d}"
        )

        question = (
            item.get("question")
            or item.get("text")
            or item.get("description")
            or item.get("title")
            or ""
        )

        impact = (
            item.get("impact")
            or item.get("reason")
            or ""
        )

        priority = (
            item.get("priority")
            or item.get("severity")
            or ""
        )

        related_requirement = (
            item.get("related_requirement")
            or item.get("related_requirement_id")
            or item.get("requirement_id")
            or ""
        )

        category = (
            item.get("category")
            or item.get("type")
            or ""
        )

        return [
            question_id,
            question,
            impact,
            priority,
            related_requirement,
            category,
        ]


    append_items_sheet(
        "Clarifications",
        clarifications,
        [
            "Question ID",
            "Question",
            "Impact / Reason",
            "Priority",
            "Related Requirement",
            "Category",
        ],
        build_clarification_row,
    )

    # Sheet 5: Requirement Summary, if available
    if requirement_summary:
        summary_sheet = workbook.create_sheet("Requirement Summary")

        summary_sheet.append(
            [
                "Section",
                "ID",
                "Description",
                "Priority",
            ]
        )
        style_header_row(summary_sheet)

        def append_summary_items(section_name: str, items):
            if not items:
                return

            if isinstance(items, str):
                summary_sheet.append(
                    [
                        section_name,
                        "",
                        items,
                        "",
                    ]
                )
                return

            if isinstance(items, dict):
                summary_sheet.append(
                    [
                        section_name,
                        items.get("id", ""),
                        normalize_text_item(items),
                        items.get("priority", ""),
                    ]
                )
                return

            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        summary_sheet.append(
                            [
                                section_name,
                                item.get("id", ""),
                                normalize_text_item(item),
                                item.get("priority", ""),
                            ]
                        )
                    else:
                        summary_sheet.append(
                            [
                                section_name,
                                "",
                                str(item),
                                "",
                            ]
                        )

        append_summary_items(
            "Overview",
            requirement_summary.get("overview"),
        )
        append_summary_items(
            "Functional Requirements",
            requirement_summary.get("functional_requirements"),
        )
        append_summary_items(
            "Business Rules",
            requirement_summary.get("business_rules"),
        )
        append_summary_items(
            "Validations",
            requirement_summary.get("validations"),
        )
        append_summary_items(
            "Integrations",
            requirement_summary.get("integrations"),
        )
        append_summary_items(
            "Error Handling",
            requirement_summary.get("error_handling"),
        )
        append_summary_items(
            "Non-functional Requirements",
            requirement_summary.get("non_functional_requirements"),
        )
        append_summary_items(
            "Assumptions",
            requirement_summary.get("assumptions"),
        )
        append_summary_items(
            "Out of Scope",
            requirement_summary.get("out_of_scope"),
        )
        append_summary_items(
            "Open Questions",
            requirement_summary.get("open_questions"),
        )

        auto_format(summary_sheet)

    # Sheet 6: Sanitized Requirement
    sanitized_sheet = workbook.create_sheet("Sanitized Requirement")
    sanitized_sheet.append(
        [
            "Requirement Context",
        ]
    )
    style_header_row(sanitized_sheet)

    sanitized_sheet.append(
        [
            sanitized_requirement,
        ]
    )

    sanitized_sheet.column_dimensions["A"].width = 120
    sanitized_sheet["A2"].alignment = Alignment(
        vertical="top",
        wrap_text=True,
    )

    workbook.save(output_file)

    return output_file


def _normalize_clarifications(
    clarifications,
) -> list:
    if not clarifications:
        return []

    if isinstance(clarifications, list):
        return clarifications

    if isinstance(clarifications, dict):
        for key in [
            "clarification_questions",
            "questions",
            "clarifications",
            "items",
            "data",
        ]:
            value = clarifications.get(key)

            if isinstance(value, list):
                return value

    return []


def requirement_exists(
    ticket_id: str,
) -> bool:
    ticket_id = _safe_requirement_id(ticket_id)

    return _requirement_dir(ticket_id).exists()


def normalize_requirement_id(
    value: str,
) -> str:
    return _safe_requirement_id(value)