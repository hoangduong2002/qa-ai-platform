from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.review_session import (
    load_review_session,
    can_improve_again
)


def build_review_keyboard(ticket_id: str):
    session = load_review_session(ticket_id)

    keyboard = []

    if can_improve_again(ticket_id):
        keyboard.append(
            [
                InlineKeyboardButton(
                    (
                        "🔄 Improve Again "
                        f"({session.get('improve_iterations', 0)}/"
                        f"{session.get('max_iterations', 3)})"
                    ),
                    callback_data=f"improve:{ticket_id}"
                )
            ]
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "💬 Comment & Improve",
                    callback_data=f"comment_improve:{ticket_id}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"accept:{ticket_id}"
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)