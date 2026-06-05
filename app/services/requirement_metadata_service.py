import json

from pathlib import Path
from datetime import datetime


def get_requirement_metadata(
    ticket_id: str
):
    requirement_dir = (
        Path("requirements")
        / ticket_id
    )

    ticket_file = (
        requirement_dir
        / "ticket.json"
    )

    summary = ""

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

    created_at = datetime.fromtimestamp(
        requirement_dir.stat().st_ctime
    ).strftime(
        "%Y-%m-%d %H:%M"
    )

    return {
        "ticket_id": ticket_id,
        "summary": summary,
        "created_at": created_at
    }