from pathlib import Path
import json


def load_workspace(ticket_id: str):

    root = Path("requirements") / ticket_id

    ticket = json.loads(
        (root / "ticket.json").read_text(
            encoding="utf-8"
        )
    )

    description = (
        root / "source" / "description.md"
    ).read_text(
        encoding="utf-8"
    )

    comments_file = (
        root / "source" / "comments.md"
    )

    comments = ""

    if comments_file.exists():
        comments = comments_file.read_text(
            encoding="utf-8"
        )

    return {
        "ticket": ticket,
        "description": description,
        "comments": comments
    }