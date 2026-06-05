# app/services/requirement_resolver.py

import json
from pathlib import Path


def resolve_requirement_id(value: str) -> str | None:
    requirements_dir = Path("requirements")

    if not requirements_dir.exists():
        return None

    direct_path = requirements_dir / value

    if direct_path.exists():
        return value

    normalized_value = value.strip().lower()

    for folder in requirements_dir.iterdir():
        if not folder.is_dir():
            continue

        ticket_file = folder / "ticket.json"

        if not ticket_file.exists():
            continue

        try:
            data = json.loads(
                ticket_file.read_text(encoding="utf-8")
            )
        except Exception:
            continue

        names = [
            data.get("display_name", ""),
            data.get("summary", "")
        ]

        for name in names:
            if name.strip().lower() == normalized_value:
                return folder.name

    return None