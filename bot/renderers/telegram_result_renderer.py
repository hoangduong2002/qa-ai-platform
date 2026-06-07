from pathlib import Path

from telegram import InputFile

from bot.keyboards.app_action_keyboards import (
    build_app_actions_keyboard
)


async def send_excel_file_from_message(
    message,
    ticket_id: str,
    excel_file: str,
    caption: str | None = None
):
    excel_path = Path(excel_file)

    if not excel_path.exists():
        await message.reply_text(
            f"Excel file was not generated: {excel_file}"
        )
        return

    with excel_path.open("rb") as file:
        await message.reply_document(
            document=InputFile(
                file,
                filename=excel_path.name
            ),
            caption=caption or f"Generated Excel file: {ticket_id}"
        )


async def send_excel_file_to_chat(
    context,
    chat_id: int,
    ticket_id: str,
    excel_file: str,
    caption: str | None = None
):
    excel_path = Path(excel_file)

    if not excel_path.exists():
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Excel file was not generated: {excel_file}"
        )
        return

    with excel_path.open("rb") as file:
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(
                file,
                filename=excel_path.name
            ),
            caption=caption or f"Generated Excel file: {ticket_id}"
        )


async def send_app_result(
    message,
    ticket_id: str,
    result
):
    await message.reply_text(
        result.message,
        reply_markup=build_app_actions_keyboard(
            result.actions
        )
    )

    for file_path in result.files:
        await send_excel_file_from_message(
            message,
            ticket_id,
            file_path,
            caption="Generated Artifact"
        )