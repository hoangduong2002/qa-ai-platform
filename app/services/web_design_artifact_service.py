import json
import re
from pathlib import Path
from typing import Any

from app.services.test_structure_service import run_initial_structure_flow
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.test_structure_exporter import export_test_case_structure_to_excel
from app.utils.test_structure_store import (
    get_approved_structure_file,
    get_design_dir,
    get_latest_structure_file,
    load_approved_test_case_structure,
    load_latest_test_case_structure,
    load_structure_session,
    load_test_case_structure_review_version,
    load_test_case_structure_version,
    save_approved_test_case_structure,
    save_latest_test_case_structure,
    save_structure_session,
    save_test_case_structure_review_version,
    save_test_case_structure_version,
)
from graph.nodes.improve_test_case_structure import improve_test_case_structure
from graph.nodes.review_test_case_structure import review_test_case_structure


def _write_json(file_path: Path, data: Any) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(file_path)


def _extract_version_name(filename: str) -> str | None:
    match = re.match(r"test_case_structure_(v\d+)\.json$", filename)
    return match.group(1) if match else None


def _extract_version_number(filename: str) -> int:
    version = _extract_version_name(filename)
    if not version:
        return 999999
    return int(version.replace("v", ""))


def list_structure_versions(ticket_id: str) -> list[dict]:
    design_dir = get_design_dir(ticket_id)
    versions = []

    if get_latest_structure_file(ticket_id).exists():
        versions.append(
            {
                "version": "latest",
                "label": "Latest Draft",
                "approved": False,
            }
        )

    if get_approved_structure_file(ticket_id).exists():
        versions.append(
            {
                "version": "approved",
                "label": "Approved",
                "approved": True,
            }
        )

    if design_dir.exists():
        for file_path in sorted(
            design_dir.glob("test_case_structure_v*.json"),
            key=lambda path: _extract_version_number(path.name),
        ):
            version = _extract_version_name(file_path.name)
            if version:
                versions.append(
                    {
                        "version": version,
                        "label": version,
                        "approved": False,
                    }
                )

    return versions


def _next_structure_version(ticket_id: str) -> str:
    max_number = 0

    for item in list_structure_versions(ticket_id):
        version = item.get("version", "")
        if re.match(r"v\d+$", version):
            max_number = max(max_number, int(version.replace("v", "")))

    return f"v{max_number + 1}"


def _resolve_structure_review_version(ticket_id: str, version: str) -> str:
    if version == "latest":
        session = load_structure_session(ticket_id)
        return session.get("current_version") or "v1"
    return version


def get_structure_version(ticket_id: str, version: str = "latest") -> dict:
    if version == "approved":
        return load_approved_test_case_structure(ticket_id)

    if version == "latest":
        return load_latest_test_case_structure(ticket_id)

    return load_test_case_structure_version(ticket_id, version)


def get_structure_version_json(ticket_id: str, version: str = "latest") -> str:
    structure = get_structure_version(ticket_id, version)
    if not structure:
        return ""

    return json.dumps(structure, indent=2, ensure_ascii=False)


def generate_structure_for_web(ticket_id: str) -> dict:
    return run_initial_structure_flow(ticket_id)


def save_structure_json_as_new_version(
    ticket_id: str,
    structure_json: str,
) -> str:
    try:
        structure = json.loads(structure_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON: {error}") from error

    if not isinstance(structure, dict):
        raise ValueError("Structure JSON must be an object.")

    new_version = _next_structure_version(ticket_id)

    save_test_case_structure_version(ticket_id, structure, new_version)
    save_latest_test_case_structure(ticket_id, structure)

    session = load_structure_session(ticket_id)
    session["current_version"] = new_version
    session["approved"] = False
    session["waiting_human_review"] = True
    save_structure_session(ticket_id, session)

    return new_version


def approve_structure_version(ticket_id: str, version: str) -> dict:
    structure = get_structure_version(ticket_id, version)
    if not structure:
        raise ValueError(f"No structure found for version: {version}")

    save_approved_test_case_structure(ticket_id, structure)

    session = load_structure_session(ticket_id)
    session["approved"] = True
    session["approved_version"] = version
    session["waiting_human_review"] = False
    save_structure_session(ticket_id, session)

    return structure


def export_structure_version_to_excel(
    ticket_id: str,
    version: str = "latest",
) -> Path:
    structure = get_structure_version(ticket_id, version)
    if not structure:
        raise ValueError(f"No structure found for version: {version}")

    review = get_structure_review(ticket_id, version)
    excel_file = export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=structure,
        review=review or {},
    )

    return Path(excel_file)


def get_structure_session_for_web(ticket_id: str) -> dict:
    return load_structure_session(ticket_id)


def get_structure_review(ticket_id: str, version: str = "latest") -> dict:
    review_version = _resolve_structure_review_version(ticket_id, version)
    return load_test_case_structure_review_version(ticket_id, review_version)


def get_structure_review_json(ticket_id: str, version: str = "latest") -> str:
    review = get_structure_review(ticket_id, version)
    if not review:
        return ""

    return json.dumps(review, indent=2, ensure_ascii=False)


def self_review_structure_version(ticket_id: str, version: str) -> dict:
    structure = get_structure_version(ticket_id, version)
    if not structure:
        raise ValueError(f"No structure found for version: {version}")

    review_version = _resolve_structure_review_version(ticket_id, version)

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["test_case_structure"] = structure
    state["structure_review_comments"] = []

    review_result = review_test_case_structure(state)
    state.update(review_result)

    review = state.get("test_case_structure_review", {})

    save_test_case_structure_review_version(
        ticket_id=ticket_id,
        review=review,
        version=review_version,
    )

    session = load_structure_session(ticket_id)
    session["last_review_version"] = review_version
    session["waiting_human_review"] = True
    save_structure_session(ticket_id, session)

    export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=structure,
        review=review,
    )

    return review


def _review_to_comment(review: dict) -> str:
    return json.dumps(
        {
            "summary": review.get("summary", ""),
            "issues": review.get("issues", []),
            "gaps": review.get("gaps", []),
            "recommendations": review.get("recommendations", []),
        },
        ensure_ascii=False,
        indent=2,
    )


def improve_structure_from_comment(
    ticket_id: str,
    version: str,
    comment: str,
) -> str:
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Improve comment is required.")

    structure = get_structure_version(ticket_id, version)
    if not structure:
        raise ValueError(f"No structure found for version: {version}")

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["test_case_structure"] = structure
    state["structure_review_comments"] = [comment]

    improve_result = improve_test_case_structure(state)
    state.update(improve_result)

    improved_structure = state.get("test_case_structure")
    if not improved_structure:
        raise ValueError("Improve structure failed.")

    new_version = _next_structure_version(ticket_id)

    save_test_case_structure_version(ticket_id, improved_structure, new_version)
    save_latest_test_case_structure(ticket_id, improved_structure)

    session = load_structure_session(ticket_id)
    session["current_version"] = new_version
    session["approved"] = False
    session["waiting_human_review"] = True
    session["last_improve_source"] = "human_or_ai_review"
    save_structure_session(ticket_id, session)

    export_test_case_structure_to_excel(
        ticket_id=ticket_id,
        structure=improved_structure,
        review={},
    )

    return new_version


def improve_structure_from_ai_review(ticket_id: str, version: str) -> str:
    review = get_structure_review(ticket_id, version)
    if not review:
        raise ValueError("No AI structure review found.")

    return improve_structure_from_comment(
        ticket_id=ticket_id,
        version=version,
        comment=_review_to_comment(review),
    )


def improve_structure_with_comment_for_web(
    ticket_id: str,
    comment: str,
) -> dict:
    comment = (comment or "").strip()

    if not comment:
        raise ValueError("Improve comment is required.")

    return run_structure_comment_improve(
        ticket_id=ticket_id,
        comment=comment,
    )