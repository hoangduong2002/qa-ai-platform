import json
from pathlib import Path


MAX_ITERATIONS = 3


def get_session_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "review"
        / "review_session.json"
    )


def load_review_session(
    ticket_id: str
) -> dict:

    session_file = get_session_file(
        ticket_id
    )

    if not session_file.exists():
        return {
            "improve_iterations": 0,
            "max_iterations": MAX_ITERATIONS,
            "accepted": False
        }

    return json.loads(
        session_file.read_text(
            encoding="utf-8"
        )
    )


def save_review_session(
    ticket_id: str,
    session: dict
):

    session_file = get_session_file(
        ticket_id
    )

    session_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    session_file.write_text(
        json.dumps(
            session,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


def increment_improve_iteration(
    ticket_id: str
) -> dict:

    session = load_review_session(
        ticket_id
    )

    session["improve_iterations"] = (
        session.get("improve_iterations", 0)
        + 1
    )

    save_review_session(
        ticket_id,
        session
    )

    return session


def mark_accepted(
    ticket_id: str
) -> dict:

    session = load_review_session(
        ticket_id
    )

    session["accepted"] = True

    save_review_session(
        ticket_id,
        session
    )

    return session


def can_improve_again(
    ticket_id: str
) -> bool:

    session = load_review_session(
        ticket_id
    )

    return (
        session.get("improve_iterations", 0)
        < session.get("max_iterations", MAX_ITERATIONS)
        and not session.get("accepted", False)
    )