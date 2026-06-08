import json
from pathlib import Path
from typing import Any


def get_design_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "design"


def get_structure_session_file(ticket_id: str) -> Path:
    return get_design_dir(ticket_id) / "structure_session.json"


def get_latest_structure_file(ticket_id: str) -> Path:
    return get_design_dir(ticket_id) / "test_case_structure.json"


def get_approved_structure_file(ticket_id: str) -> Path:
    return get_design_dir(ticket_id) / "approved_test_case_structure.json"


def get_structure_version_file(ticket_id: str, version: str) -> Path:
    return get_design_dir(ticket_id) / f"test_case_structure_{version}.json"


def get_structure_review_version_file(ticket_id: str, version: str) -> Path:
    return get_design_dir(ticket_id) / f"test_case_structure_review_{version}.json"


def _read_json(file_path: Path, default: Any):
    if not file_path.exists():
        return default

    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON file: {file_path}. Error: {error}") from error


def _write_json(file_path: Path, data: Any) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(file_path)


def default_structure_session() -> dict:
    return {
        "current_version": None,
        "review_iterations": 0,
        "max_review_iterations": 3,
        "approved": False,
        "waiting_human_review": False,
        "pending_generation_after_approval": False,
    }


def load_structure_session(ticket_id: str) -> dict:
    saved_session = _read_json(
        get_structure_session_file(ticket_id),
        default_structure_session(),
    )

    session = default_structure_session()
    session.update(saved_session or {})
    return session


def save_structure_session(ticket_id: str, session: dict) -> str:
    merged_session = default_structure_session()
    merged_session.update(session or {})
    return _write_json(get_structure_session_file(ticket_id), merged_session)


def save_test_case_structure_version(
    ticket_id: str,
    structure: dict,
    version: str,
) -> str:
    return _write_json(
        get_structure_version_file(ticket_id, version),
        structure,
    )


def load_test_case_structure_version(ticket_id: str, version: str) -> dict:
    return _read_json(
        get_structure_version_file(ticket_id, version),
        {},
    )


def save_test_case_structure_review_version(
    ticket_id: str,
    review: dict,
    version: str,
) -> str:
    return _write_json(
        get_structure_review_version_file(ticket_id, version),
        review,
    )


def load_test_case_structure_review_version(ticket_id: str, version: str) -> dict:
    return _read_json(
        get_structure_review_version_file(ticket_id, version),
        {},
    )


def save_latest_test_case_structure(ticket_id: str, structure: dict) -> str:
    return _write_json(
        get_latest_structure_file(ticket_id),
        structure,
    )


def load_latest_test_case_structure(ticket_id: str) -> dict:
    session = load_structure_session(ticket_id)
    current_version = session.get("current_version")

    if current_version:
        versioned_structure = load_test_case_structure_version(
            ticket_id,
            current_version,
        )
        if versioned_structure:
            return versioned_structure

    return _read_json(
        get_latest_structure_file(ticket_id),
        {},
    )


def save_test_case_structure_review(ticket_id: str, review: dict) -> str:
    return save_test_case_structure_review_version(
        ticket_id=ticket_id,
        review=review,
        version="latest",
    )


def save_approved_test_case_structure(ticket_id: str, structure: dict) -> str:
    if not structure:
        raise ValueError("Cannot approve empty test case structure.")

    return _write_json(
        get_approved_structure_file(ticket_id),
        structure,
    )


def load_approved_test_case_structure(ticket_id: str) -> dict:
    return _read_json(
        get_approved_structure_file(ticket_id),
        {},
    )


def has_test_case_structure(ticket_id: str) -> bool:
    session = load_structure_session(ticket_id)
    current_version = session.get("current_version")

    if current_version:
        if get_structure_version_file(ticket_id, current_version).exists():
            return True

    return get_latest_structure_file(ticket_id).exists()


def has_approved_test_case_structure(ticket_id: str) -> bool:
    return get_approved_structure_file(ticket_id).exists()


def ensure_approved_test_case_structure(ticket_id: str) -> dict:
    structure = load_approved_test_case_structure(ticket_id)

    if not structure:
        raise ValueError(
            f"No approved test case structure found for {ticket_id}."
        )

    return structure


def set_pending_generation_after_approval(
    ticket_id: str,
    pending: bool,
) -> str:
    session = load_structure_session(ticket_id)
    session["pending_generation_after_approval"] = pending
    return save_structure_session(ticket_id, session)


def has_pending_generation_after_approval(ticket_id: str) -> bool:
    session = load_structure_session(ticket_id)
    return bool(session.get("pending_generation_after_approval", False))