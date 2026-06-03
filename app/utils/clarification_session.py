import json
import re
from pathlib import Path


def get_clarification_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "clarification_answers.json"
    )


def parse_clarification_answers(
    raw_answers: str
) -> dict:

    answers = {}

    pattern = re.compile(
        r"^(Q\d+)\s*:\s*(.+)$",
        re.IGNORECASE
    )

    for line in raw_answers.splitlines():

        line = line.strip()

        if not line:
            continue

        match = pattern.match(line)

        if match:

            question_id = match.group(1).upper()
            answer = match.group(2).strip()

            answers[question_id] = answer

    return answers


def save_clarification_answers(
    ticket_id: str,
    raw_answers: str
):

    parsed_answers = parse_clarification_answers(
        raw_answers
    )

    output = {
        "raw_answers": raw_answers,
        "answers": parsed_answers
    }

    output_file = get_clarification_file(
        ticket_id
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return str(output_file)


def load_clarification_answers(
    ticket_id: str
) -> dict:

    input_file = get_clarification_file(
        ticket_id
    )

    if not input_file.exists():
        return {}

    return json.loads(
        input_file.read_text(
            encoding="utf-8"
        )
    )
    
def get_clarification_questions_snapshot_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "clarification_questions_snapshot.json"
    )


def save_clarification_questions_snapshot(
    ticket_id: str,
    clarifications: dict
):

    output_file = get_clarification_questions_snapshot_file(
        ticket_id
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        json.dumps(
            clarifications,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return str(output_file)


def load_clarification_questions_snapshot(
    ticket_id: str
) -> dict:

    input_file = get_clarification_questions_snapshot_file(
        ticket_id
    )

    if not input_file.exists():
        return {}

    return json.loads(
        input_file.read_text(
            encoding="utf-8"
        )
    )