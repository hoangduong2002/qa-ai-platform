import json
from pathlib import Path


def rename_requirement(ticket_id: str, new_name: str) -> bool:
    requirement_dir = Path("requirements") / ticket_id
    requirement_dir.mkdir(parents=True, exist_ok=True)

    ticket_file = requirement_dir / "ticket.json"

    data = {}

    if ticket_file.exists():
        try:
            data = json.loads(ticket_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["ticket_id"] = ticket_id
    data["summary"] = new_name
    data["display_name"] = new_name

    ticket_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return True