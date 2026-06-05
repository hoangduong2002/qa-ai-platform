from pathlib import Path

from app.utils.file_extractors import (
    extract_file_text
)

from datetime import datetime
from pathlib import Path

import json
from datetime import datetime
from pathlib import Path


def apply_clarification_answers_to_requirement(
    ticket_id: str
):
    root = Path("requirements") / ticket_id

    clarifications_file = (
        root / "analysis" / "clarifications.json"
    )

    answers_file = (
        root / "analysis" / "clarification_answers.json"
    )

    if not answers_file.exists():
        return False

    clarifications = {}

    if clarifications_file.exists():
        clarifications = json.loads(
            clarifications_file.read_text(
                encoding="utf-8"
            )
        )

    answers_data = json.loads(
        answers_file.read_text(
            encoding="utf-8"
        )
    )

    questions = clarifications.get(
        "clarification_questions",
        []
    )

    answers = answers_data.get(
        "answers",
        {}
    )

    output_dir = (
        root
        / "source"
        / "clarification_answers"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    existing_files = sorted(
        output_dir.glob(
            "clarification_answers_*.md"
        )
    )

    next_index = len(existing_files) + 1

    output_file = (
        output_dir
        / f"clarification_answers_{next_index:03d}.md"
    )

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    content = (
        f"# Clarification Answers {next_index}\n\n"
        f"Created: {timestamp}\n\n"
    )

    for question in questions:
        question_id = question.get(
            "question_id",
            ""
        )

        answer = answers.get(
            question_id,
            ""
        )

        if not answer:
            continue

        content += (
            f"## {question_id}\n\n"
            f"Question:\n"
            f"{question.get('question', '')}\n\n"
            f"Answer:\n"
            f"{answer}\n\n"
            f"Impact:\n"
            f"{question.get('impact', '')}\n\n"
            "---\n\n"
        )

    output_file.write_text(
        content,
        encoding="utf-8"
    )

    invalidate_after_clarification_promoted(
        ticket_id
    )

    return True


def append_requirement_text(
    ticket_id: str,
    text: str
):
    notes_dir = (
        Path("requirements")
        / ticket_id
        / "source"
        / "additional_notes"
    )

    notes_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    existing_notes = sorted(
        notes_dir.glob(
            "note_*.md"
        )
    )

    next_index = (
        len(existing_notes)
        + 1
    )

    note_file = (
        notes_dir
        / f"note_{next_index:03d}.md"
    )

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    note_file.write_text(
        f"""# Additional Note {next_index}

Created: {timestamp}

{text}
""",
        encoding="utf-8"
    )

    invalidate_analysis(
        ticket_id
    )


def add_requirement_file(
    ticket_id: str,
    uploaded_file_path: Path,
    file_name: str
):
    source_dir = (
        Path("requirements")
        / ticket_id
        / "source"
    )

    original_dir = (
        source_dir
        / "original_files"
    )

    extracted_dir = (
        source_dir
        / "extracted"
    )

    original_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    extracted_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    target_file = (
        original_dir
        / file_name
    )

    target_file.write_bytes(
        uploaded_file_path.read_bytes()
    )

    extracted_text = extract_file_text(
        target_file
    )

    extracted_file = (
        extracted_dir
        / f"{target_file.stem}.md"
    )

    extracted_file.write_text(
        extracted_text,
        encoding="utf-8"
    )

    invalidate_analysis(
        ticket_id
    )


def invalidate_analysis(
    ticket_id: str
):
    root = Path("requirements") / ticket_id

    files_to_remove = [
        root / "analysis" / "requirement_analysis.json",
        root / "analysis" / "clarifications.json",
        root / "analysis" / "clarification_answers.json",
        root / "analysis" / "clarification_questions_snapshot.json",
        root / "analysis" / "requirement_summary.json",
        root / "analysis" / "test_scope.json",
        root / "analysis" / "scenarios.json",
        root / "testcases" / "testcases.json",
        root / "testcases" / "improved_testcases.json",
        root / "review" / "coverage_review.json",
        root / "review" / "final_coverage_review.json",
        root / "review" / "review_session.json",
    ]

    for file_path in files_to_remove:
        if file_path.exists():
            file_path.unlink()
            
def invalidate_after_clarification_promoted(ticket_id: str):
    root = Path("requirements") / ticket_id

    files_to_remove = [
        root / "analysis" / "requirement_summary.json",
        root / "analysis" / "test_scope.json",
        root / "scenarios" / "scenarios.json",
        root / "testcases" / "testcases.json",
        root / "testcases" / "improved_testcases.json",
        root / "review" / "coverage_review.json",
        root / "review" / "final_coverage_review.json",
        root / "review" / "review_session.json",
    ]

    for file_path in files_to_remove:
        if file_path.exists():
            file_path.unlink()