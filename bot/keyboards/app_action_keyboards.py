from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_app_actions_keyboard(actions):
    if not actions:
        return None

    rows = []
    row = []

    for action in actions:
        row.append(
            InlineKeyboardButton(
                action.label,
                callback_data=(
                    f"{action.action}:"
                    f"{action.ticket_id}"
                )
            )
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return InlineKeyboardMarkup(rows)