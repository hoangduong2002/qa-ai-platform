import json
from pathlib import Path


def get_design_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "design"


def get_structure_session_file(ticket_id: str) -> Path:
    return get_design_dir(ticket_id) / "structure_session.json"


def load_structure_session(ticket_id: str) -> dict:
    file_path = get_structure_session_file(ticket_id)

    if not file_path.exists():
        return {
            "current_version": None,
            "review_iterations": 0,
            "max_review_iterations": 3,
            "approved": False,
            "waiting_human_review": False
        }

    return json.loads(file_path.read_text(encoding="utf-8"))


def save_structure_session(ticket_id: str, session: dict):
    file_path = get_structure_session_file(ticket_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(
        json.dumps(session, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return str(file_path)


def save_test_case_structure_version(
    ticket_id: str,
    structure: dict,
    version: str
):
    file_path = (
        get_design_dir(ticket_id)
        / f"test_case_structure_{version}.json"
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(
        json.dumps(structure, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return str(file_path)


def load_test_case_structure_version(
    ticket_id: str,
    version: str
):
    file_path = (
        get_design_dir(ticket_id)
        / f"test_case_structure_{version}.json"
    )

    if not file_path.exists():
        return {}

    return json.loads(file_path.read_text(encoding="utf-8"))


def save_test_case_structure_review_version(
    ticket_id: str,
    review: dict,
    version: str
):
    file_path = (
        get_design_dir(ticket_id)
        / f"test_case_structure_review_{version}.json"
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return str(file_path)


def save_latest_test_case_structure(
    ticket_id: str,
    structure: dict
):
    file_path = get_design_dir(ticket_id) / "test_case_structure.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(
        json.dumps(structure, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return str(file_path)


def load_latest_test_case_structure(ticket_id: str):
    session = load_structure_session(ticket_id)
    version = session.get("current_version")

    if version:
        return load_test_case_structure_version(ticket_id, version)

    file_path = get_design_dir(ticket_id) / "test_case_structure.json"

    if not file_path.exists():
        return {}

    return json.loads(file_path.read_text(encoding="utf-8"))


def save_approved_test_case_structure(ticket_id: str, structure: dict):
    file_path = get_design_dir(ticket_id) / "approved_test_case_structure.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(
        json.dumps(structure, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return str(file_path)

def save_test_case_structure_review(
    ticket_id: str,
    review: dict
):
    return save_test_case_structure_review_version(
        ticket_id,
        review,
        "latest"
    )


def has_approved_test_case_structure(
    ticket_id: str
) -> bool:

    file_path = (
        get_design_dir(ticket_id)
        / "approved_test_case_structure.json"
    )

    return file_path.exists()


def has_test_case_structure(
    ticket_id: str
) -> bool:
    latest_file = (
        get_design_dir(ticket_id)
        / "test_case_structure.json"
    )

    session = load_structure_session(
        ticket_id
    )

    version = session.get(
        "current_version"
    )

    if version:
        version_file = (
            get_design_dir(ticket_id)
            / f"test_case_structure_{version}.json"
        )

        return version_file.exists()

    return latest_file.exists()


def has_approved_test_case_structure(
    ticket_id: str
) -> bool:
    file_path = (
        get_design_dir(ticket_id)
        / "approved_test_case_structure.json"
    )

    return file_path.exists()