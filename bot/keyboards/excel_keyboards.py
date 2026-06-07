from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_excel_keyboard(
    ticket_id: str,
    excel_files: list[str]
):
    if not excel_files:
        return None

    keyboard = []

    for file_name in excel_files[-5:]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📥 {file_name}",
                    callback_data=f"download:{ticket_id}:{file_name}"
                )
            ]
        )

    return InlineKeyboardMarkup(keyboard)