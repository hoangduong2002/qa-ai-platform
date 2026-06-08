from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.review_session import (
    load_review_session,
    can_improve_again
)


def build_review_keyboard(ticket_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "AI Review",
                    callback_data=f"testcase_ai_review:{ticket_id}",
                ),
                InlineKeyboardButton(
                    "Comment & Improve",
                    callback_data=f"testcase_comment:{ticket_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "Accept",
                    callback_data=f"testcase_accept:{ticket_id}",
                ),
            ],
        ]
    )