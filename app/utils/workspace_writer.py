import json
from pathlib import Path
from datetime import datetime


def create_workspace_from_text(
    ticket_id: str,
    requirement_text: str,
    source: str = "telegram_text"
):
    root = Path("requirements") / ticket_id
    source_dir = root / "source"

    source_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    ticket_data = {
        "ticket_id": ticket_id,
        "summary": f"Telegram Requirement {ticket_id}",
        "status": "Draft",
        "source": source,
        "created_at": datetime.now().isoformat()
    }

    (root / "ticket.json").write_text(
        json.dumps(
            ticket_data,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    (source_dir / "description.md").write_text(
        requirement_text,
        encoding="utf-8"
    )

    (source_dir / "comments.md").write_text(
        "",
        encoding="utf-8"
    )

    return str(root)