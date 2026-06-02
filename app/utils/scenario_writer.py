import json
from pathlib import Path


def save_scenarios(
    ticket_id: str,
    scenarios: list
):

    output_file = (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "scenarios.json"
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        json.dumps(
            scenarios,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )