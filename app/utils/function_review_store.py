import json
from pathlib import Path
from typing import Any


def get_review_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "review"


def get_function_review_dir(ticket_id: str) -> Path:
    return get_review_dir(ticket_id) / "functions"


def get_function_coverage_review_file(ticket_id: str, function_id: str) -> Path:
    return get_function_review_dir(ticket_id) / f"{function_id}_coverage_review.json"


def get_master_coverage_review_file(ticket_id: str) -> Path:
    return get_review_dir(ticket_id) / "coverage_review.json"


def get_function_coverage_manifest_file(ticket_id: str) -> Path:
    return get_review_dir(ticket_id) / "function_coverage_review_manifest.json"


def save_json(file_path: Path, data: Any) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(file_path)


def save_function_coverage_review(
    ticket_id: str,
    function_id: str,
    review: dict,
) -> str:
    return save_json(
        get_function_coverage_review_file(ticket_id, function_id),
        review,
    )


def save_master_coverage_review(
    ticket_id: str,
    review: dict,
) -> str:
    return save_json(
        get_master_coverage_review_file(ticket_id),
        review,
    )


def save_function_coverage_manifest(
    ticket_id: str,
    manifest: dict,
) -> str:
    return save_json(
        get_function_coverage_manifest_file(ticket_id),
        manifest,
    )