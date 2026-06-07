from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_clarification_keyboard(
    ticket_id: str,
    mode: str
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✍️ Answer Clarifications",
                    callback_data=f"answer_clarifications:{mode}:{ticket_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⏭️ Skip Clarifications",
                    callback_data=f"skip_clarifications:{mode}:{ticket_id}"
                )
            ]
        ]
    )