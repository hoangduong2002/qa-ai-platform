import json
from pathlib import Path


def load_analysis(ticket_id: str):

    file_path = (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "requirement_analysis.json"
    )

    return json.loads(
        file_path.read_text(
            encoding="utf-8"
        )
    )