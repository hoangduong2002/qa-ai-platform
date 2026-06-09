import hashlib
from pathlib import Path

from app.utils.requirement_sanitizer import (
    clean_requirement_text,
    is_sanitizer_enabled,
)


def sanitize_requirement_for_analysis(
    ticket_id: str,
    raw_requirement: str,
) -> str:
    if not is_sanitizer_enabled():
        return raw_requirement

    sanitized_requirement = clean_requirement_text(
        raw_requirement,
    )

    analysis_dir = (
        Path("requirements")
        / ticket_id
        / "analysis"
    )

    analysis_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_hash = hashlib.sha256(
        raw_requirement.encode("utf-8")
    ).hexdigest()

    sanitized_file = (
        analysis_dir
        / "sanitized_requirement.md"
    )

    hash_file = (
        analysis_dir
        / "sanitized_requirement.sha256"
    )

    sanitized_file.write_text(
        sanitized_requirement,
        encoding="utf-8",
    )

    hash_file.write_text(
        raw_hash,
        encoding="utf-8",
    )

    return sanitized_requirement