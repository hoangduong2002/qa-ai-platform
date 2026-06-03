import json
from pathlib import Path


def get_history_file(ticket_id: str) -> Path:
    return (
        Path("requirements")
        / ticket_id
        / "review"
        / "improvement_history.json"
    )


def load_improvement_history(ticket_id: str) -> list:
    file_path = get_history_file(ticket_id)

    if not file_path.exists():
        return []

    data = json.loads(
        file_path.read_text(encoding="utf-8")
    )

    return data.get("history", [])


def save_improvement_history_item(
    ticket_id: str,
    version: str,
    iteration: int,
    coverage_score,
    improvement_score,
    note: str = ""
):
    history = load_improvement_history(ticket_id)

    history.append(
        {
            "version": version,
            "iteration": iteration,
            "coverage_score": coverage_score,
            "improvement_score": improvement_score,
            "note": note
        }
    )

    file_path = get_history_file(ticket_id)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path.write_text(
        json.dumps(
            {"history": history},
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )