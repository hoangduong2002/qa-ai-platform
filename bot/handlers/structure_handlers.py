from telegram import Update
from telegram.ext import ContextTypes

from app.application.generation_orchestrator import prepare_generation
from app.application.structure_review_orchestrator import (
    self_review_structure as self_review_structure_app,
    comment_improve_structure as comment_improve_structure_app,
    wait_structure as wait_structure_app,
    approve_structure as approve_structure_app,
)
from app.services.requirement_resolver import resolve_requirement_id
from app.utils.test_structure_store import (
    has_pending_generation_after_approval,
    set_pending_generation_after_approval,
)
from bot.renderers.telegram_result_renderer import send_app_result


def get_message(update):
    if update.message:
        return update.message

    if update.callback_query:
        return update.callback_query.message

    return None


async def structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        message = get_message(update)
        await message.reply_text("Usage:\n/structure <requirement_id>")
        return

    raw_id = " ".join(context.args)
    ticket_id = resolve_requirement_id(raw_id)

    if not ticket_id:
        message = get_message(update)
        await message.reply_text(f"Requirement not found: {raw_id}")
        return

    message = get_message(update)

    await message.reply_text(
        f"Preparing test case structure for {ticket_id}..."
    )

    try:
        result = prepare_generation(ticket_id)
        await send_app_result(message, ticket_id, result)
    except Exception as error:
        await message.reply_text(
            f"Failed to prepare test case structure:\n{error}"
        )


async def handle_structure_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    after_approve_callback=None,
) -> bool:
    query = update.callback_query
    data = query.data

    if data.startswith("structure_self_review:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        await query.message.reply_text(
            f"Running structure self review for {ticket_id}..."
        )

        try:
            result = self_review_structure_app(ticket_id)
            await send_app_result(query.message, ticket_id, result)
        except Exception as error:
            await query.message.reply_text(
                f"Failed to self review structure:\n{error}"
            )

        return True

    if data.startswith("structure_comment:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        context.user_data["comment_structure_ticket_id"] = ticket_id

        await query.message.reply_text(
            "Please enter your structure review comment."
        )

        return True

    if data.startswith("structure_wait:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        try:
            result = wait_structure_app(ticket_id)
            await query.message.reply_text(result.message)
        except Exception as error:
            await query.message.reply_text(
                f"Failed to pause structure review:\n{error}"
            )

        return True

    if data.startswith("structure_approve:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        try:
            pending_generation = has_pending_generation_after_approval(
                ticket_id
            )

            result = approve_structure_app(ticket_id)

            if pending_generation and after_approve_callback:
                set_pending_generation_after_approval(
                    ticket_id,
                    False,
                )

                await query.message.reply_text(
                    f"✅ Test case structure approved for {ticket_id}.\n\n"
                    f"Continuing generation automatically because this "
                    f"structure review was started from /generate."
                )

                await after_approve_callback(
                    query.message,
                    ticket_id,
                )

                return True

            await query.message.reply_text(result.message)

        except Exception as error:
            await query.message.reply_text(
                f"Failed to approve structure:\n{error}"
            )

        return True

    return False


async def handle_structure_comment_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    ticket_id = context.user_data.get("comment_structure_ticket_id")

    if not ticket_id:
        return False

    comment = update.message.text.strip()
    context.user_data.pop("comment_structure_ticket_id", None)

    message = get_message(update)

    await message.reply_text(
        f"Received your structure review comment.\n\n"
        f"Requirement: {ticket_id}\n"
        f"Updating structure now..."
    )

    try:
        result = comment_improve_structure_app(ticket_id, comment)
        await send_app_result(message, ticket_id, result)
    except Exception as error:
        await message.reply_text(
            f"Failed to update structure:\n{error}"
        )

    return True