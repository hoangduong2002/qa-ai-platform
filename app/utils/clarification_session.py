import json
import re
from pathlib import Path
from datetime import datetime


def get_clarification_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "clarification_answers.json"
    )


def get_clarifications_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "analysis"
        / "clarifications.json"
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


def load_clarifications(
    ticket_id: str
) -> dict:

    input_file = get_clarifications_file(
        ticket_id
    )

    if not input_file.exists():
        return {}

    return json.loads(
        input_file.read_text(
            encoding="utf-8"
        )
    )


def build_answered_clarifications(
    ticket_id: str,
    parsed_answers: dict
) -> list:

    clarifications = load_clarifications(
        ticket_id
    )

    questions = clarifications.get(
        "clarification_questions",
        []
    )

    question_map = {
        item.get("question_id", "").upper(): item
        for item in questions
    }

    answered = []

    now = datetime.now().isoformat()

    for question_id, answer in parsed_answers.items():

        question = question_map.get(
            question_id,
            {}
        )

        answered.append(
            {
                "question_id": question_id,
                "id": question.get(
                    "id",
                    question_id
                ),
                "question": question.get(
                    "question",
                    ""
                ),
                "category": question.get(
                    "category",
                    "Other"
                ),
                "impact": question.get(
                    "impact",
                    "Medium"
                ),
                "reason": question.get(
                    "reason",
                    ""
                ),
                "suggested_options": question.get(
                    "suggested_options",
                    []
                ),
                "free_text_allowed": question.get(
                    "free_text_allowed",
                    True
                ),
                "selected_option_key": "",
                "selected_option_label": "",
                "custom_answer": answer,
                "final_answer": answer,
                "answer": answer,
                "answered_at": now
            }
        )

    return answered


def save_clarification_answers(
    ticket_id: str,
    raw_answers: str
):

    parsed_answers = parse_clarification_answers(
        raw_answers
    )

    answered_clarifications = build_answered_clarifications(
        ticket_id,
        parsed_answers
    )

    output = {
        "raw_answers": raw_answers,
        "answers": parsed_answers,
        "answered_clarifications": answered_clarifications
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
