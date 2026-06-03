import json
from pathlib import Path


def get_review_comments_file(
    ticket_id: str
) -> Path:

    return (
        Path("requirements")
        / ticket_id
        / "review"
        / "review_comments.json"
    )


def load_review_comments(
    ticket_id: str
) -> list:

    input_file = get_review_comments_file(
        ticket_id
    )

    if not input_file.exists():
        return []

    data = json.loads(
        input_file.read_text(
            encoding="utf-8"
        )
    )

    return data.get(
        "comments",
        []
    )


def _next_comment_id(
    comments: list
) -> str:

    return (
        "RC"
        + str(len(comments) + 1).zfill(3)
    )


def save_review_comment(
    ticket_id: str,
    iteration: int,
    comment: str
):

    comments = load_review_comments(
        ticket_id
    )

    comment_id = _next_comment_id(
        comments
    )

    comments.append(
        {
            "comment_id": comment_id,
            "iteration": iteration,
            "comment": comment
        }
    )

    output_file = get_review_comments_file(
        ticket_id
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        json.dumps(
            {
                "comments": comments
            },
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return str(output_file)