import json
from pathlib import Path


def save_testcases(
    ticket_id: str,
    testcases: list
):

    output_file = (
        Path("requirements")
        / ticket_id
        / "testcases"
        / "testcases.json"
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        json.dumps(
            testcases,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )