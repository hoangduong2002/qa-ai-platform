import json

from pathlib import Path

from app.services.requirement_status_service import (
    get_requirement_status
)


def list_requirements():

    requirements_dir = Path(
        "requirements"
    )

    items = []

    if not requirements_dir.exists():
        return items

    for folder in sorted(
        requirements_dir.iterdir(),
        reverse=True
    ):

        if not folder.is_dir():
            continue

        ticket_id = folder.name

        ticket_file = (
            folder
            / "ticket.json"
        )

        summary = ""

        created_at = ""

        if ticket_file.exists():

            try:

                data = json.loads(
                    ticket_file.read_text(
                        encoding="utf-8"
                    )
                )

                summary = data.get(
                    "summary",
                    ""
                )

            except Exception:
                pass

        created_at = (
            folder.stat()
            .st_ctime
        )

        from datetime import datetime

        created_at = datetime.fromtimestamp(
            created_at
        ).strftime(
            "%Y-%m-%d %H:%M"
        )

        icon, status = (
            get_requirement_status(
                ticket_id
            )
        )

        items.append(
            {
                "ticket_id": ticket_id,
                "summary": summary,
                "created_at": created_at,
                "status": status,
                "status_icon": icon
            }
        )

    return items