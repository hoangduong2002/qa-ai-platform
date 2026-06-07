from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_structure_review_keyboard(ticket_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Self Review",
                    callback_data=f"structure_self_review:{ticket_id}"
                ),
                InlineKeyboardButton(
                    "Comment",
                    callback_data=f"structure_comment:{ticket_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Wait",
                    callback_data=f"structure_wait:{ticket_id}"
                ),
                InlineKeyboardButton(
                    "Approve",
                    callback_data=f"structure_approve:{ticket_id}"
                )
            ]
        ]
    )