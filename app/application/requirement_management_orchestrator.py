import os
import stat
from datetime import datetime

from pathlib import Path
import shutil

from app.application.response_models import (
    AppResult
)

from app.services.requirement_list_service import (
    list_requirements
)

from app.services.requirement_update_service import (
    append_requirement_text
)


def _remove_readonly(func, path, exc_info):
    try:
        os.chmod(
            path,
            stat.S_IWRITE
        )

        func(path)

    except Exception:
        raise


def list_requirement_items() -> AppResult:
    requirements = list_requirements()

    if not requirements:
        return AppResult(
            status="NO_REQUIREMENTS",
            message="No requirements found."
        )

    lines = [
        "Requirements:",
        ""
    ]

    for item in requirements:
        lines.append(
            (
                f"- {item.get('ticket_id', '')} | "
                f"{item.get('summary', '')} | "
                f"Status: {item.get('status', '')} | "
                f"Created: {item.get('created_at', '')}"
            )
        )

    return AppResult(
        status="REQUIREMENTS_LISTED",
        message="\n".join(lines),
        data={
            "requirements": requirements
        }
    )


def get_requirement_status(
    ticket_id: str
) -> AppResult:
    root = (
        Path("requirements")
        / ticket_id
    )

    if not root.exists():
        return AppResult(
            status="NOT_FOUND",
            message=f"Requirement not found: {ticket_id}"
        )

    ticket_file = root / "ticket.json"

    summary = ""

    if ticket_file.exists():
        try:
            import json

            ticket = json.loads(
                ticket_file.read_text(
                    encoding="utf-8"
                )
            )

            summary = ticket.get(
                "summary",
                ""
            )

        except Exception:
            summary = ""

    artifacts = {
        "analysis": (
            root
            / "analysis"
            / "requirement_analysis.json"
        ).exists(),
        "clarifications": (
            root
            / "analysis"
            / "clarifications.json"
        ).exists(),
        "clarification_answers": (
            root
            / "analysis"
            / "clarification_answers.json"
        ).exists(),
        "requirement_summary": (
            root
            / "analysis"
            / "requirement_summary.json"
        ).exists(),
        "test_case_structure": (
            root
            / "design"
            / "test_case_structure.json"
        ).exists(),
        "approved_structure": (
            root
            / "design"
            / "approved_test_case_structure.json"
        ).exists(),
        "testcases": (
            root
            / "testcases"
            / "testcases.json"
        ).exists(),
        "coverage_review": (
            root
            / "review"
            / "coverage_review.json"
        ).exists(),
        "final_review": (
            root
            / "review"
            / "final_coverage_review.json"
        ).exists(),
    }

    lines = [
        f"Status for {ticket_id}",
        "",
        f"Summary: {summary}",
        "",
        "Artifacts:"
    ]

    for key, value in artifacts.items():
        icon = "✅" if value else "❌"
        lines.append(
            f"{icon} {key}"
        )

    return AppResult(
        status="STATUS_LOADED",
        message="\n".join(lines),
        data={
            "ticket_id": ticket_id,
            "summary": summary,
            "artifacts": artifacts
        }
    )


def add_requirement_text(
    ticket_id: str,
    text: str
) -> AppResult:
    append_requirement_text(
        ticket_id,
        text
    )

    return AppResult(
        status="REQUIREMENT_UPDATED",
        message=(
            f"Additional requirement text added to {ticket_id}.\n"
            f"Analysis, structure, scenarios, and test cases were invalidated."
        )
    )


def delete_requirement(
    ticket_id: str
) -> AppResult:
    root = (
        Path("requirements")
        / ticket_id
    )

    if not root.exists():
        return AppResult(
            status="NOT_FOUND",
            message=f"Requirement not found: {ticket_id}"
        )

    shutil.rmtree(
        root,
        onerror=_remove_readonly
    )

    return AppResult(
        status="REQUIREMENT_DELETED",
        message=f"Requirement deleted: {ticket_id}"
    )


def delete_all_requirements() -> AppResult:
    root = Path("requirements")

    if not root.exists():
        root.mkdir(
            parents=True,
            exist_ok=True
        )

        return AppResult(
            status="ALL_REQUIREMENTS_DELETED",
            message="All requirements deleted."
        )

    trash_root = Path(
        "requirements_deleted"
    )

    trash_root.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    target = (
        trash_root
        / f"requirements_{timestamp}"
    )

    try:
        root.rename(
            target
        )

        root.mkdir(
            parents=True,
            exist_ok=True
        )

        return AppResult(
            status="ALL_REQUIREMENTS_DELETED",
            message=(
                "All requirements were moved to trash.\n\n"
                f"Trash folder: {target}"
            )
        )

    except Exception as error:
        return AppResult(
            status="DELETE_FAILED",
            message=(
                "Failed to delete all requirements because some files "
                "are currently locked by another process.\n\n"
                f"Error: {error}\n\n"
                "Please close VSCode preview, Excel, or any program "
                "opening files under the requirements folder and try again."
            )
        )


def rename_requirement(
    ticket_id: str,
    new_summary: str
) -> AppResult:
    import json

    root = (
        Path("requirements")
        / ticket_id
    )

    if not root.exists():
        return AppResult(
            status="NOT_FOUND",
            message=f"Requirement not found: {ticket_id}"
        )

    ticket_file = (
        root
        / "ticket.json"
    )

    ticket = {}

    if ticket_file.exists():
        try:
            ticket = json.loads(
                ticket_file.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            ticket = {}

    ticket["summary"] = new_summary

    ticket_file.write_text(
        json.dumps(
            ticket,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return AppResult(
        status="REQUIREMENT_RENAMED",
        message=(
            f"Requirement renamed.\n\n"
            f"ID: {ticket_id}\n"
            f"New summary: {new_summary}"
        )
    )