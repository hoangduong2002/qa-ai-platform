from datetime import datetime
from pathlib import Path

from app.utils.workspace_writer import create_workspace_from_text
from app.utils.file_extractors import extract_file_text


def generate_ticket_id(prefix: str = "TG") -> str:
    return (
        prefix
        + "-"
        + datetime.now().strftime("%Y%m%d%H%M%S")
    )


def create_requirement_from_text(
    requirement_text: str,
    source: str = "telegram_text"
) -> str:

    ticket_id = generate_ticket_id()

    create_workspace_from_text(
        ticket_id,
        requirement_text,
        source=source
    )

    return ticket_id


def create_requirement_from_uploaded_file(
    telegram_file_name: str,
    local_file_path: Path
) -> tuple[str, str]:

    ticket_id = generate_ticket_id()

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
        / telegram_file_name
    )

    target_file.write_bytes(
        local_file_path.read_bytes()
    )

    extracted_text = extract_file_text(
        target_file
    )

    extracted_file = (
        extracted_dir
        / "extracted_requirement.md"
    )

    extracted_file.write_text(
        extracted_text,
        encoding="utf-8"
    )

    create_workspace_from_text(
        ticket_id,
        extracted_text,
        source=f"telegram_file:{telegram_file_name}"
    )

    return ticket_id, extracted_text