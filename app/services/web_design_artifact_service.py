import json
import re
from pathlib import Path
from typing import Any

from app.services.test_structure_service import (
    run_initial_structure_flow,
    run_structure_comment_improve,
)
from app.utils.test_structure_exporter import (
    export_test_case_structure_to_excel,
)
from app.utils.test_structure_store import (
    get_approved_structure_file,
    get_design_dir,
    get_latest_structure_file,
    get_structure_version_file,
    load_approved_test_case_structure,
    load_latest_test_case_structure,
    load_structure_session,
    load_test_case_structure_version,
    save_approved_test_case_structure,
    save_latest_test_case_structure,
    save_structure_session,
    save_test_case_structure_version,
)

from app.utils.artifact_loader import (
    load_ticket_artifacts,
)
from graph.nodes.review_test_case_structure import (
    review_test_case_structure,
)
from app.utils.test_structure_store import (
    load_test_case_structure_review_version,
    save_test_case_structure_review_version,
)


def _read_json(
    file_path: Path,
    default: Any = None,
):
    if not file_path.exists():
        return default

    try:
        return json.loads(
            file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        )
    except json.JSONDecodeError:
        return default


def _write_json(
    file_path: Path,
    data: Any,
) -> str:
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return str(file_path)


def list_structure_versions(
    ticket_id: str,
) -> list[dict]:
    design_dir = get_design_dir(ticket_id)

    versions = []

    latest_file = get_latest_structure_file(ticket_id)
    approved_file = get_approved_structure_file(ticket_id)

    if latest_file.exists():
        versions.append(
            {
                "version": "latest",
                "label": "Latest Draft",
                "file": latest_file.name,
                "approved": False,
            }
        )

    if approved_file.exists():
        versions.append(
            {
                "version": "approved",
                "label": "Approved",
                "file": approved_file.name,
                "approved": True,
            }
        )

    if design_dir.exists():
        version_files = sorted(
            design_dir.glob("test_case_structure_v*.json"),
            key=lambda path: _extract_version_number(path.name),
        )

        for file_path in version_files:
            version = _extract_version_name(file_path.name)

            if not version:
                continue

            versions.append(
                {
                    "version": version,
                    "label": f"Version {version}",
                    "file": file_path.name,
                    "approved": False,
                }
            )

    return versions


def _extract_version_name(
    filename: str,
) -> str | None:
    match = re.match(
        r"test_case_structure_(v\d+)\.json$",
        filename,
    )

    if not match:
        return None

    return match.group(1)


def _extract_version_number(
    filename: str,
) -> int:
    version = _extract_version_name(filename)

    if not version:
        return 999999

    return int(
        version.replace("v", "")
    )


def _next_structure_version(
    ticket_id: str,
) -> str:
    versions = list_structure_versions(ticket_id)

    max_number = -1

    for item in versions:
        version = item.get("version", "")

        if not re.match(r"v\d+$", version):
            continue

        number = int(
            version.replace("v", "")
        )

        max_number = max(
            max_number,
            number,
        )

    return f"v{max_number + 1}"


def get_structure_version(
    ticket_id: str,
    version: str = "latest",
) -> dict:
    if version == "approved":
        return load_approved_test_case_structure(
            ticket_id
        )

    if version == "latest":
        return load_latest_test_case_structure(
            ticket_id
        )

    return load_test_case_structure_version(
        ticket_id,
        version,
    )


def get_structure_version_json(
    ticket_id: str,
    version: str = "latest",
) -> str:
    structure = get_structure_version(
        ticket_id=ticket_id,
        version=version,
    )

    if not structure:
        return ""

    return json.dumps(
        structure,
        indent=2,
        ensure_ascii=False,
    )


def generate_structure_for_web(
    ticket_id: str,
) -> dict:
    state = run_initial_structure_flow(
        ticket_id
    )

    return state


def save_structure_json_as_new_version(
    ticket_id: str,
    structure_json: str,
) -> str:
    try:
        structure = json.loads(
            structure_json
        )
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON: {error}"
        ) from error

    if not isinstance(structure, dict):
        raise ValueError(
            "Structure JSON must be an object."
        )

    new_version = _next_structure_version(
        ticket_id
    )

    save_test_case_structure_version(
        ticket_id=ticket_id,
        structure=structure,
        version=new_version,
    )

    save_latest_test_case_structure(
        ticket_id=ticket_id,
        structure=structure,
    )

    session = load_structure_session(
        ticket_id
    )

    session["current_version"] = new_version
    session["approved"] = False
    session["waiting_human_review"] = True

    save_structure_session(
        ticket_id,
        session,
    )

    return new_version


def approve_structure_version(
    ticket_id: str,
    version: str,
) -> dict:
    structure = get_structure_version(
        ticket_id=ticket_id,
        version=version,
    )

    if not structure:
        raise ValueError(
            f"No structure found for version: {version}"
        )

    save_approved_test_case_structure(
        ticket_id=ticket_id,
        structure=structure,
    )

    session = load_structure_session(
        ticket_id
    )

    session["approved"] = True
    session["approved_version"] = version
    session["waiting_human_review"] = False

    save_structure_session(
        ticket_id,
        session,
    )

    return structure


def export_structure_version_to_excel(
    ticket_id: str,
    version: str = "latest",
) -> Path:
    structure = get_structure_version(
        ticket_id=ticket_id,
        version=version,
    )

    if not structure:
        raise ValueError(
            f"No structure found for version: {version}"
        )

    review = {}

    excel_file = export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=structure,
        review=review,
    )

    return Path(excel_file)


def get_structure_session_for_web(
    ticket_id: str,
) -> dict:
    return load_structure_session(
        ticket_id
    )


def get_structure_review(
    ticket_id: str,
    version: str = "latest",
) -> dict:
    if version == "approved":
        version = "approved"

    if version == "latest":
        session = load_structure_session(ticket_id)
        version = session.get("current_version") or "v1"

    return load_test_case_structure_review_version(
        ticket_id=ticket_id,
        version=version,
    )


def get_structure_review_json(
    ticket_id: str,
    version: str = "latest",
) -> str:
    review = get_structure_review(
        ticket_id=ticket_id,
        version=version,
    )

    if not review:
        return ""

    return json.dumps(
        review,
        indent=2,
        ensure_ascii=False,
    )


def self_review_structure_version(
    ticket_id: str,
    version: str,
) -> dict:
    structure = get_structure_version(
        ticket_id=ticket_id,
        version=version,
    )

    if not structure:
        raise ValueError(
            f"No structure found for version: {version}"
        )

    if version == "latest":
        session = load_structure_session(ticket_id)
        review_version = session.get("current_version") or "v1"
    else:
        review_version = version

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["test_case_structure"] = structure
    state["structure_review_comments"] = []

    review_result = review_test_case_structure(state)
    state.update(review_result)

    review = state.get(
        "test_case_structure_review",
        {},
    )

    save_test_case_structure_review_version(
        ticket_id=ticket_id,
        review=review,
        version=review_version,
    )

    session = load_structure_session(ticket_id)
    session["last_review_version"] = review_version
    session["waiting_human_review"] = True

    save_structure_session(
        ticket_id,
        session,
    )

    export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=structure,
        review=review,
    )

    return review


def improve_structure_with_comment_for_web(
    ticket_id: str,
    comment: str,
) -> dict:
    comment = comment.strip()

    if not comment:
        raise ValueError(
            "Improve comment is required."
        )

    result = run_structure_comment_improve(
        ticket_id=ticket_id,
        comment=comment,
    )

    return result