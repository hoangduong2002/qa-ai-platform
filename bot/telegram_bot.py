import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

from telegram import (
    Update,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

from graph.testcase_graph import graph

from app.utils.excel_exporter import export_testcases_to_excel
from app.utils.workspace_writer import create_workspace_from_text
from app.utils.file_extractors import extract_file_text
from app.utils.artifact_loader import load_ticket_artifacts

from app.services.improve_cycle_service import run_improve_cycle

from app.utils.review_session import (
    load_review_session,
    save_review_session,
    increment_improve_iteration,
    mark_accepted,
    can_improve_again
)


load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


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
                "✅ Accept",
                callback_data=f"accept:{ticket_id}"
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def build_excel_keyboard(ticket_id: str, excel_files: list[str]):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "QA AI Bot ready.\n\n"
        "Commands:\n"
        "/generate DEMO-001\n"
        "/generate_text <requirement>\n"
        "/status <ticket_id>\n\n"
        "Or upload requirement file:\n"
        "- .txt\n"
        "- .md\n"
        "- .docx\n"
        "- .pptx\n"
        "- .png\n"
        "- .jpg\n"
        "- .jpeg\n"
        "- .webp"
    )


async def send_excel_file(
    update: Update,
    ticket_id: str,
    excel_file: str
):
    excel_path = Path(excel_file)

    if not excel_path.exists():
        await update.message.reply_text(
            f"Excel file was not generated: {excel_file}"
        )
        return

    with excel_path.open("rb") as file:
        await update.message.reply_document(
            document=InputFile(
                file,
                filename=f"{ticket_id}_testcases.xlsx"
            ),
            caption="Generated testcases Excel file"
        )


async def send_excel_file_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    ticket_id: str,
    excel_file: str
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
            caption=f"Generated testcases Excel file: {ticket_id}"
        )


async def process_ticket(update: Update, ticket_id: str):
    result = graph.invoke(
        {
            "ticket_id": ticket_id
        }
    )

    save_review_session(
        ticket_id,
        {
            "improve_iterations": 0,
            "max_iterations": 3,
            "accepted": False
        }
    )

    analysis = result.get("analysis", {})
    scenarios = result.get("scenarios", [])

    original_testcases = result.get("testcases", [])
    improved_testcases = result.get("improved_testcases", [])

    testcases = improved_testcases or original_testcases

    review = result.get("coverage_review", {})
    final_review = result.get("final_coverage_review", {})

    message = (
        f"✅ Done: {ticket_id}\n\n"
        f"Scenarios: {len(scenarios)}\n"
        f"Testcases: {len(testcases)}\n\n"
        f"Initial Coverage: {review.get('coverage_score', 'N/A')}\n"
        f"Final Coverage: {final_review.get('coverage_score', 'N/A')}\n\n"
        f"Remaining Gaps:\n"
    )

    gaps = (
        final_review.get("remaining_gaps")
        or review.get("missing_coverage")
        or []
    )

    if gaps:
        for item in gaps[:5]:
            message += f"- {item}\n"
    else:
        message += "- None\n"

    message += "\nDo you want AI to improve test cases again?"

    await update.message.reply_text(
        message,
        reply_markup=build_review_keyboard(ticket_id)
    )

    excel_file = export_testcases_to_excel(
        ticket_id,
        analysis,
        scenarios,
        testcases,
        review,
        final_review,
        version="v0"
    )

    await send_excel_file(
        update,
        ticket_id,
        excel_file
    )


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /generate DEMO-001"
        )
        return

    ticket_id = context.args[0]

    await update.message.reply_text(
        f"Generating testcases for {ticket_id}..."
    )

    await process_ticket(update, ticket_id)


async def generate_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/generate_text User can create account using email and password"
        )
        return

    requirement_text = " ".join(context.args)

    ticket_id = (
        "TG-"
        + datetime.now().strftime("%Y%m%d%H%M%S")
    )

    create_workspace_from_text(
        ticket_id,
        requirement_text
    )

    await update.message.reply_text(
        f"Requirement received.\n"
        f"Generated ID: {ticket_id}\n"
        f"Processing..."
    )

    await process_ticket(update, ticket_id)


async def handle_requirement_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    document = update.message.document

    if not document:
        await update.message.reply_text("No document found.")
        return

    ticket_id = (
        "TG-"
        + datetime.now().strftime("%Y%m%d%H%M%S")
    )

    await update.message.reply_text(
        f"File received: {document.file_name}\n"
        f"Generated ID: {ticket_id}\n"
        f"Downloading..."
    )

    source_dir = (
        Path("requirements")
        / ticket_id
        / "source"
    )

    original_dir = source_dir / "original_files"
    extracted_dir = source_dir / "extracted"

    original_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    telegram_file = await document.get_file()

    file_path = original_dir / document.file_name

    await telegram_file.download_to_drive(
        custom_path=str(file_path)
    )

    await update.message.reply_text(
        "File downloaded. Extracting text and image-based requirements..."
    )

    try:
        extracted_text = extract_file_text(file_path)

    except Exception as error:
        await update.message.reply_text(
            f"Failed to extract file content: {error}"
        )
        return

    if not extracted_text.strip():
        await update.message.reply_text(
            "No readable requirement text found in the uploaded file."
        )
        return

    extracted_file = extracted_dir / "extracted_requirement.md"

    extracted_file.write_text(
        extracted_text,
        encoding="utf-8"
    )

    create_workspace_from_text(
        ticket_id,
        extracted_text,
        source=f"telegram_file:{document.file_name}"
    )

    await update.message.reply_text(
        f"Requirement extracted.\n"
        f"Processing {ticket_id}..."
    )

    await process_ticket(update, ticket_id)


async def handle_review_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    parts = query.data.split(":")

    action = parts[0]

    if len(parts) < 2:
        await query.message.reply_text(
            "Invalid action."
        )
        return

    ticket_id = parts[1]

    if action == "download":
        if len(parts) < 3:
            await query.message.reply_text(
                "Invalid download request."
            )
            return

        file_name = parts[2]

        excel_file = (
            Path("requirements")
            / ticket_id
            / "exports"
            / file_name
        )

        if not excel_file.exists():
            await query.message.reply_text(
                f"File not found: {file_name}"
            )
            return

        with excel_file.open("rb") as file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(
                    file,
                    filename=file_name
                ),
                caption=file_name
            )

        return

    if action == "accept":
        mark_accepted(ticket_id)

        await query.edit_message_text(
            f"✅ Accepted: {ticket_id}\n\n"
            f"The generated test cases are finalized."
        )

        return

    if action == "improve":
        if not can_improve_again(ticket_id):
            await query.edit_message_text(
                f"⚠️ Maximum improvement iterations reached for {ticket_id}.\n\n"
                f"Please review manually or accept the current version."
            )
            return

        session = increment_improve_iteration(ticket_id)

        await query.edit_message_text(
            f"🔄 Improving test cases for {ticket_id}...\n"
            f"Iteration: {session.get('improve_iterations')}/"
            f"{session.get('max_iterations')}"
        )

        result = run_improve_cycle(ticket_id)

        analysis = result.get("analysis", {})
        scenarios = result.get("scenarios", [])

        testcases = (
            result.get("improved_testcases")
            or result.get("testcases", [])
        )

        review = result.get("coverage_review", {})
        final_review = result.get("final_coverage_review", {})

        session = load_review_session(ticket_id)

        version = f"v{session.get('improve_iterations', 0)}"

        message = (
            f"✅ Improvement completed: {ticket_id}\n\n"
            f"Iteration: {session.get('improve_iterations')}/"
            f"{session.get('max_iterations')}\n"
            f"Scenarios: {len(scenarios)}\n"
            f"Testcases: {len(testcases)}\n\n"
            f"Initial Coverage: {review.get('coverage_score', 'N/A')}\n"
            f"Final Coverage: {final_review.get('coverage_score', 'N/A')}\n"
            f"Improvement: +{final_review.get('improvement_score', 0)}\n\n"
            f"Remaining Gaps:\n"
        )

        gaps = final_review.get("remaining_gaps") or []

        if gaps:
            for item in gaps[:5]:
                message += f"- {item}\n"
        else:
            message += "- None\n"

        if can_improve_again(ticket_id):
            message += "\nDo you want AI to improve test cases again?"
        else:
            message += "\nMaximum improvement iterations reached."

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message,
            reply_markup=build_review_keyboard(ticket_id)
        )

        excel_file = export_testcases_to_excel(
            ticket_id,
            analysis,
            scenarios,
            testcases,
            review,
            final_review,
            version=version
        )

        await send_excel_file_to_chat(
            context,
            query.message.chat_id,
            ticket_id,
            excel_file
        )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage: /status TG-20260603120000"
        )
        return

    ticket_id = context.args[0]

    data = load_ticket_artifacts(ticket_id)

    scenarios = data.get("scenarios", [])
    testcases = data.get("testcases", [])
    review = data.get("coverage_review", {})
    final_review = data.get("final_coverage_review", {})
    session = data.get("session", {})

    exports_dir = (
        Path("requirements")
        / ticket_id
        / "exports"
    )

    excel_files = []

    if exports_dir.exists():
        excel_files = sorted(
            [
                file.name
                for file in exports_dir.glob("*.xlsx")
            ]
        )

    message = (
        f"📊 Status: {ticket_id}\n\n"
        f"Scenarios: {len(scenarios)}\n"
        f"Testcases: {len(testcases)}\n\n"
        f"Initial Coverage: {review.get('coverage_score', 'N/A')}\n"
        f"Final Coverage: {final_review.get('coverage_score', 'N/A')}\n\n"
        f"Improve Iterations: "
        f"{session.get('improve_iterations', 0)}/"
        f"{session.get('max_iterations', 3)}\n"
        f"Accepted: {session.get('accepted', False)}\n\n"
        f"Excel Files:\n"
    )

    if excel_files:
        for file_name in excel_files[-5:]:
            message += f"- {file_name}\n"
    else:
        message += "- None\n"

    await update.message.reply_text(
        message,
        reply_markup=build_excel_keyboard(
            ticket_id,
            excel_files
        )
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("generate", generate)
    )

    app.add_handler(
        CommandHandler("generate_text", generate_text)
    )

    app.add_handler(
        CommandHandler("status", status)
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_requirement_file
        )
    )

    app.add_handler(
        CallbackQueryHandler(handle_review_action)
    )

    app.run_polling()


if __name__ == "__main__":
    main()