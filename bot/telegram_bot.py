import os
import shutil
import asyncio
import logging

from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

from telegram import (
    Update,
    InputFile,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

from graph.requirement_question_graph import (
    requirement_question_graph
)

from graph.requirement_summary_graph import (
    requirement_summary_graph
)

from graph.test_generation_graph import (
    test_generation_graph
)


from app.utils.requirement_intelligence_exporter import (
    export_requirement_intelligence_to_excel
)

from app.utils.workspace_writer import (
    create_workspace_from_text
)

from app.utils.file_extractors import (
    extract_file_text
)

from app.utils.artifact_loader import (
    load_ticket_artifacts
)

from app.utils.clarification_session import (
    save_clarification_answers,
    save_clarification_questions_snapshot
)

from app.services.improve_cycle_service import (
    run_improve_cycle
)

from app.utils.review_session import (
    load_review_session,
    save_review_session,
    increment_improve_iteration,
    mark_accepted,
    can_improve_again
)

from app.utils.review_comment_session import (
    save_review_comment
)

from app.utils.improvement_history import (
    save_improvement_history_item
)

from app.services.requirement_workspace_service import (
    create_requirement_from_text
)

from app.services.requirement_resolver import (
    resolve_requirement_id
)

from app.services.requirement_update_service import (
    apply_clarification_answers_to_requirement
)

from app.services.report_service import (
    generate_system_report
)

from app.services.test_structure_service import (
    run_initial_structure_flow
)

from app.utils.test_structure_store import (
    load_test_case_structure_version,
    save_approved_test_case_structure,
    load_structure_session,
    set_pending_generation_after_approval,
    load_approved_test_case_structure
)

from app.application.generation_orchestrator import (
    prepare_generation,
    build_structured_generation_state,
)

from app.application.export_orchestrator import (
    export_generation_result_to_excel,
    save_generation_history,
)

from app.application.structure_review_orchestrator import (
    self_review_structure as self_review_structure_app,
    comment_improve_structure as comment_improve_structure_app,
    wait_structure as wait_structure_app,
    approve_structure as approve_structure_app
)

from app.application.requirement_management_orchestrator import (
    list_requirement_items,
    get_requirement_status,
    add_requirement_text,
    delete_requirement,
    delete_all_requirements,
    rename_requirement
)

from bot.keyboards.structure_keyboards import (
    build_structure_review_keyboard
)

from bot.keyboards.review_keyboards import (
    build_review_keyboard
)

from bot.keyboards.clarification_keyboards import (
    build_clarification_keyboard
)

from bot.keyboards.excel_keyboards import (
    build_excel_keyboard
)

from bot.renderers.telegram_result_renderer import (
    send_app_result,
    send_excel_file_from_message,
    send_excel_file_to_chat
)

from bot.handlers.structure_handlers import (
    structure,
    handle_structure_callback,
    handle_structure_comment_text
)

from app.exporters.function_based_excel_exporter import (
    export_function_based_testcases_to_excel,
)

from app.services.testcase_review_service import run_testcase_ai_review
from bot.renderers.testcase_review_text_renderer import (
    render_testcase_review_chat_summary,
)

from app.services.jira_requirement_service import (
    create_requirement_from_jira,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ADD_TEXT_STATE = "add_text"
ADD_FILE_STATE = "add_file"


def get_message(update):
    if update.message:
        return update.message

    if update.callback_query:
        return update.callback_query.message

    return None


def extract_clarification_questions(result: dict) -> list:
    clarifications = result.get("clarifications", {})

    return clarifications.get(
        "clarification_questions",
        []
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = get_message(update)

    await message.reply_text(
        """
        🤖 QA AI Platform Bot

        Recommended Workflow
        --------------------
        1. Create or analyze a requirement
        2. Answer clarification questions
        3. Review Requirement Intelligence Excel
        4. Generate test cases
        5. Review coverage
        6. Improve or accept test cases


        Requirement Intelligence
        ------------------------
        /analyze <ticket_id>
        Analyze an existing requirement and generate clarification questions.

        /analyze_text <requirement>
        Create a new requirement from text, then analyze it.

        When clarification questions appear:
        - Answer Clarifications: provide answers like:
        Q001: answer...
        Q002: answer...
        - Skip Clarifications: continue with open questions.

        /structure <ticket_id>
        Generate function-based test case structure, run AI review, improve it, export Excel, and ask for human approval.

        Structure Review Actions:
        - AI Review: AI reviews and improves the current structure again.
        - Comment: provide human feedback and let AI update the structure.
        - Wait: pause review and resume later with /structure <ticket_id>.
        - Approve: approve the current structure and save final approved version.

        Test Case Generation
        --------------------
        /generate <ticket_id>
        Generate test cases from an existing requirement.
        If the requirement was already analyzed and answered, it will continue from the existing analysis.

        /generate_text <requirement>
        Create a new requirement from text, analyze it, then generate test cases.


        Requirement Updates
        -------------------
        /add_text <ticket_id>
        Add more requirement information as an additional note.
        This invalidates current analysis and test case artifacts.

        /add_file <ticket_id>
        Upload an additional requirement file.
        Supported files: TXT, DOCX, PPTX, PNG, JPG, JPEG, WebP.
        This invalidates current analysis and test case artifacts.

        /rename <ticket_id>
        Rename the requirement display name.


        Requirement Management
        ----------------------
        /requirements
        List all requirements with name, created date, current status, and quick commands.

        /status <ticket_id>
        Show detailed status, coverage, improvement progress, and downloadable Excel files.

        /delete <ticket_id>
        Delete one requirement.

        /delete_all
        Delete all requirements. Confirmation is required.
        
        /report
        Generate system report: requirements, test cases, improvements, AI usage, model, runtime, and tokens.


        Review & Improvement Buttons
        ----------------------------
        Improve Again
        AI improves test cases using coverage review.

        Comment & Improve
        You provide review comments, and AI improves test cases based on your comment.

        Accept
        Mark the current test cases as accepted.


        Upload Behavior
        ---------------
        You can upload requirement files directly.
        By default, uploaded files create a new requirement and start the generate flow.

        For adding a file to an existing requirement:
        1. Run /add_file <ticket_id>
        2. Upload the file
        """
    )
    

async def report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = get_message(update)

    await message.reply_text(
        "Generating QA AI system report..."
    )

    report_file = generate_system_report()

    await send_excel_file_from_message(
        update.message,
        "SYSTEM",
        report_file,
        caption="QA AI Platform Usage Report"
    )

    
async def add_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage: /add_text <requirement_id>"
        )
        return

    raw_id = " ".join(context.args)

    ticket_id = resolve_requirement_id(
        raw_id
    )

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    context.user_data[
        "add_text_ticket_id"
    ] = ticket_id

    message = get_message(update)

    await message.reply_text(
        (
            f"Please send additional requirement text for {ticket_id}."
        )
    )
    
async def add_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:

        message = get_message(update)

        await message.reply_text(
            "Usage:\n"
            "/add_file TG-20260604080006"
        )

        return

    raw_id = " ".join(context.args)

    ticket_id = resolve_requirement_id(raw_id)

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    context.user_data[
        "add_file_ticket_id"
    ] = ticket_id

    message = get_message(update)

    await message.reply_text(
        f"Please upload file for {ticket_id}"
    )


async def export_requirement_intelligence(
    message,
    ticket_id: str
):
    artifacts = load_ticket_artifacts(ticket_id)

    excel_file = export_requirement_intelligence_to_excel(
        ticket_id=ticket_id,
        analysis=artifacts.get("analysis", {}),
        clarifications=artifacts.get("clarifications", {}),
        clarification_answers=artifacts.get("clarification_answers", {}),
        requirement_summary=artifacts.get("requirement_summary", {})
    )

    await send_excel_file_from_message(
        message,
        ticket_id,
        excel_file,
        caption=f"Requirement Intelligence Excel file: {ticket_id}"
    )


async def run_requirement_summary(
    ticket_id: str
):
    requirement_summary_graph.invoke(
        {
            "ticket_id": ticket_id
        }
    )

    return load_ticket_artifacts(ticket_id)


async def continue_generation_with_structure_gate(
    message,
    ticket_id: str,
    prepare_requirement_context: bool = True,
):
    if prepare_requirement_context:
        await message.reply_text(
            f"Preparing requirement summary and generation context for {ticket_id}..."
        )

        await run_requirement_summary(ticket_id)

    await message.reply_text(
        f"Checking approved test case structure for {ticket_id}..."
    )

    generation_gate_result = prepare_generation(ticket_id)

    if generation_gate_result.status != "READY_TO_GENERATE":
        set_pending_generation_after_approval(
            ticket_id,
            True,
        )

        await send_app_result(
            message,
            ticket_id,
            generation_gate_result,
        )
        return

    await message.reply_text(generation_gate_result.message)

    generation_state = build_structured_generation_state(ticket_id)

    if not generation_state.get("approved_test_case_structure"):
        raise ValueError(
            "approved_test_case_structure was not added to generation_state."
        )

    await message.reply_text(
        "Starting structured generation pipeline:\n"
        "1. Generate scenarios\n"
        "2. Generate test cases by main function\n"
        "3. Coverage review by deterministic check\n"
        "4. Improve test cases if needed\n"
        "5. Final review by deterministic check\n"
        "6. Export Excel"
    )

    await run_generation(
        message,
        ticket_id,
        generation_state,
    )


def export_generated_testcases_excel(
    ticket_id: str,
    result: dict,
    version: str = "latest"
) -> str:
    """
    Export generated/improved test cases using the function-based Excel exporter.

    The exporter may already return a versioned file.
    This wrapper creates a versioned copy only when needed.
    """

    artifacts = load_ticket_artifacts(ticket_id)

    testcases = (
        result.get("improved_testcases")
        or result.get("testcases")
        or artifacts.get("improved_testcases")
        or artifacts.get("testcases")
        or []
    )

    coverage_review = (
        result.get("coverage_review")
        or artifacts.get("coverage_review")
        or {}
    )

    final_coverage_review = (
        result.get("final_coverage_review")
        or artifacts.get("final_coverage_review")
        or {}
    )

    approved_structure = (
        result.get("approved_test_case_structure")
        or artifacts.get("approved_test_case_structure")
        or {}
    )

    excel_file = export_function_based_testcases_to_excel(
        ticket_id=ticket_id,
        testcases=testcases,
        coverage_review=coverage_review,
        final_coverage_review=final_coverage_review,
        approved_structure=approved_structure,
    )

    if not version:
        return excel_file

    source_file = Path(excel_file)

    versioned_file = (
        source_file.parent
        / f"{ticket_id}_function_based_testcases_{version}.xlsx"
    )

    if source_file.resolve() == versioned_file.resolve():
        return str(source_file)

    shutil.copyfile(source_file, versioned_file)

    return str(versioned_file)


async def self_review_structure(update, context):

    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage:\n/self_review_structure <ticket_id>"
        )
        return

    ticket_id = context.args[0]

    message = get_message(update)

    await message.reply_text(
        f"Running AI review and improvement for structure: {ticket_id}"
    )

    state = run_initial_structure_flow(
        ticket_id
    )

    message = get_message(update)

    await message.reply_text(
        "AI review and structure improvement completed."
    )

    await send_excel_file_from_message(
        update.message,
        ticket_id,
        state["structure_excel_file"],
        caption="Updated Test Case Structure"
    )


async def run_generation(
    message,
    ticket_id: str,
    generation_state: dict
):
    if not hasattr(message, "reply_text"):
        raise TypeError(
            f"run_generation expected Telegram Message, got {type(message)}"
        )

    await message.reply_text(
        f"Running test case generation graph for {ticket_id}..."
    )

    result = test_generation_graph.invoke(generation_state)

    await message.reply_text(
        f"Test case generation completed for {ticket_id}."
    )

    save_review_session(
        ticket_id,
        {
            "review_iterations": 0,
            "improve_iterations": 0,
            "max_iterations": 3,
            "accepted": False,
        }
    )

    scenarios = result.get("scenarios", [])
    testcases = result.get("testcases", [])

    summary_message = (
        f"✅ Test cases generated: {ticket_id}\n\n"
        f"Scenarios: {len(scenarios)}\n"
        f"Testcases: {len(testcases)}\n\n"
        f"Please review the Excel file.\n\n"
        f"Choose an action:\n"
        f"- AI Review: run AI review only\n"
        f"- Comment: improve test cases with your feedback\n"
        f"- Accept: accept current test cases"
    )

    excel_file = export_generated_testcases_excel(
        ticket_id=ticket_id,
        result=result,
        version="v0",
    )

    await send_excel_file_from_message(
        message,
        ticket_id,
        excel_file,
        caption=f"Generated testcases Excel file: {ticket_id}"
    )

    await message.reply_text(
        summary_message,
        reply_markup=build_review_keyboard(ticket_id),
    )

async def ask_clarifications(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    ticket_id: str,
    questions: list,
    mode: str
):
    max_questions = int(os.getenv("MAX_CLARIFICATIONS_PER_ROUND", "5"))

    questions = questions[:max_questions]

    clarification_message = (
        f"❓ Clarifications found for {ticket_id}\n\n"
    )

    for item in questions:
        clarification_message += (
            f"{item.get('question_id', '')}: "
            f"{item.get('question', '')}\n"
            f"Priority: {item.get('priority') or item.get('impact', 'N/A')}\n"
            f"Impact: {item.get('impact_area', item.get('category', 'N/A'))}\n\n"
        )

    clarification_message += (
        f"Showing {len(questions)} clarification question(s).\n\n"
        "Please answer in this format:\n"
        "Q001: your answer\n"
        "Q002: your answer\n\n"
        "Do you want to answer these clarifications?"
    )

    await message.reply_text(
        clarification_message,
        reply_markup=build_clarification_keyboard(
            ticket_id,
            mode,
        ),
    )


async def run_requirement_questions(
    ticket_id: str
):
    result = requirement_question_graph.invoke(
        {
            "ticket_id": ticket_id
        }
    )

    save_clarification_questions_snapshot(
        ticket_id,
        result.get("clarifications", {})
    )

    return result


async def process_ticket(update: Update, ticket_id: str):
    message = get_message(update)

    artifacts = load_ticket_artifacts(ticket_id)

    questions = (
        artifacts
        .get("clarifications", {})
        .get("clarification_questions", [])
    )

    has_answers = bool(
        artifacts.get("clarification_answers", {})
    )

    # Existing clarification questions must be answered first.
    if questions and not has_answers:
        await message.reply_text(
            f"Existing clarification questions found for {ticket_id}.\n"
            f"Please answer them before generating test cases."
        )

        await ask_clarifications(
            message,
            None,
            ticket_id,
            questions,
            mode="generate",
        )
        return

    # If no clarification questions exist yet, analyze requirement first.
    if not questions:
        result = await run_requirement_questions(ticket_id)
        questions = extract_clarification_questions(result)

        if questions:
            await ask_clarifications(
                message,
                None,
                ticket_id,
                questions,
                mode="generate",
            )
            return

    # From this point onward, test case generation must go through structure gate.
    await continue_generation_with_structure_gate(
        get_message(update),
        ticket_id,
    )

    
async def analyze_existing_ticket(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    ticket_id: str
):
    result = await run_requirement_questions(
        ticket_id
    )

    analysis = result.get(
        "analysis",
        {}
    )

    questions = extract_clarification_questions(
        result
    )

    response_text = (
        f"✅ Requirement analysis completed: {ticket_id}\n\n"
        f"Requirement Items: "
        f"{len(analysis.get('requirement_items', []))}\n"
        f"Clarification Questions: {len(questions)}\n\n"
    )

    if questions:
        response_text += (
            "Please answer these clarification questions:\n\n"
        )

        for item in questions:
            response_text += (
                f"{item.get('question_id', '')}: "
                f"{item.get('question', '')}\n"
                f"Impact: {item.get('impact', 'N/A')}\n\n"
            )

        response_text += (
            f"Total clarification questions: {len(questions)}\n\n"
            "Do you want to answer these clarifications?"
        )

        await message.reply_text(
            response_text,
            reply_markup=build_clarification_keyboard(
                ticket_id,
                "analyze"
            )
        )

        return

    response_text += (
        "No clarification questions found. "
        "Generating requirement summary..."
    )

    await message.reply_text(
        response_text
    )

    await run_requirement_summary(
        ticket_id
    )

    await export_requirement_intelligence(
        message,
        ticket_id
    )


async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage: /analyze TG-20260603120000"
        )
        return

    raw_id = " ".join(context.args)

    ticket_id = resolve_requirement_id(raw_id)

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    message = get_message(update)

    await message.reply_text(
        f"Analyzing requirement for {ticket_id}..."
    )

    await analyze_existing_ticket(
        update.message,
        context,
        ticket_id
    )
    
async def analyze_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage:\n"
            "/analyze_text User can create account using email and password"
        )
        return

    requirement_text = " ".join(
        context.args
    )

    ticket_id = create_requirement_from_text(
        requirement_text,
        source="telegram_analyze_text"
    )

    message = get_message(update)

    await message.reply_text(
        f"Requirement created.\n"
        f"Generated ID: {ticket_id}\n"
        f"Analyzing..."
    )

    await analyze_existing_ticket(
        update.message,
        context,
        ticket_id
    )


async def generate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = get_message(update)

    if not context.args:
        await message.reply_text(
            "Usage: /generate DEMO-001"
        )
        return

    raw_id = " ".join(context.args)
    ticket_id = resolve_requirement_id(raw_id)

    if not ticket_id:
        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    await message.reply_text(
        f"Preparing structured generation for {ticket_id}...\n\n"
        f"Generation now requires an approved test case structure."
    )

    try:
        await process_ticket(update, ticket_id)
    except Exception as error:
        await message.reply_text(
            f"Failed during structured generation:\n{error}"
        )


async def generate_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage:\n"
            "/generate_text User can create account using email and password"
        )
        return

    requirement_text = " ".join(
        context.args
    )

    ticket_id = create_requirement_from_text(
        requirement_text,
        source="telegram_generate_text"
    )

    message = get_message(update)

    await message.reply_text(
        f"Requirement created.\n"
        f"Generated ID: {ticket_id}\n"
        f"Processing..."
    )

    await process_ticket(
        update,
        ticket_id
    )


async def handle_requirement_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    
    add_file_ticket_id = (
        context.user_data.get(
            "add_file_ticket_id"
        )
    )

    if add_file_ticket_id:

        from app.services.requirement_update_service import (
            add_requirement_file
        )

        document = update.message.document

        telegram_file = await document.get_file()

        temp_dir = Path("temp")
        temp_dir.mkdir(
            exist_ok=True
        )

        temp_file = (
            temp_dir
            / document.file_name
        )

        await telegram_file.download_to_drive(
            custom_path=str(temp_file)
        )

        add_requirement_file(
            add_file_ticket_id,
            temp_file,
            document.file_name
        )

        context.user_data.pop(
            "add_file_ticket_id",
            None
        )

        message = get_message(update)

        await message.reply_text(
            f"File added to requirement: {add_file_ticket_id}\n\n"
            f"Analysis artifacts invalidated.\n"
            f"Please run /analyze again."
        )

        return
    
    document = update.message.document

    if not document:
        message = get_message(update)

        await message.reply_text(
            "No document found."
        )
        return

    ticket_id = (
        "TG-"
        + datetime.now().strftime("%Y%m%d%H%M%S")
    )

    message = get_message(update)

    await message.reply_text(
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

    original_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    extracted_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    telegram_file = await document.get_file()

    file_path = original_dir / document.file_name

    await telegram_file.download_to_drive(
        custom_path=str(file_path)
    )

    message = get_message(update)

    await message.reply_text(
        "File downloaded. Extracting text and image-based requirements..."
    )

    try:
        extracted_text = extract_file_text(
            file_path
        )

    except Exception as error:
        message = get_message(update)

        await message.reply_text(
            f"Failed to extract file content: {error}"
        )
        return

    if not extracted_text.strip():
        message = get_message(update)

        await message.reply_text(
            "No readable requirement text found in the uploaded file."
        )
        return

    extracted_file = (
        extracted_dir
        / "extracted_requirement.md"
    )

    extracted_file.write_text(
        extracted_text,
        encoding="utf-8"
    )

    create_workspace_from_text(
        ticket_id,
        extracted_text,
        source=f"telegram_file:{document.file_name}"
    )

    message = get_message(update)

    await message.reply_text(
        f"Requirement extracted.\n"
        f"Processing {ticket_id}..."
    )

    await analyze_existing_ticket(
        message,
        context,
        ticket_id,
    )


def run_comment_improve_testcases(
    ticket_id: str,
    comment: str,
) -> dict:

    session = load_review_session(ticket_id)
    iteration = int(session.get("improve_iterations", 0)) + 1
    max_iterations = int(session.get("max_iterations", 3))

    if iteration > max_iterations:
        raise ValueError("Maximum improve iterations reached.")

    save_review_comment(
        ticket_id,
        iteration,
        comment,
    )

    session["improve_iterations"] = iteration
    session["accepted"] = False
    save_review_session(ticket_id, session)

    result = run_improve_cycle(ticket_id)

    result["version"] = f"v{iteration}"

    return result


async def handle_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    
    logger.warning(
        "TEXT RECEIVED: %s",
        update.message.text,
    )

    logger.warning(
        "USER_DATA: %s",
        context.user_data,
    )

    handled = await handle_structure_comment_text(
        update,
        context
    )

    if handled:
        return

    message = get_message(update)
    
    #
    # Confirm delete all
    #
    if context.user_data.get(
        "confirm_delete_all"
    ):
        if (
            update.message.text.strip()
            == "1234"
        ):
            context.user_data.pop(
                "confirm_delete_all",
                None
            )

            result = delete_all_requirements()

            await message.reply_text(
                result.message
            )

            return

        context.user_data.pop(
            "confirm_delete_all",
            None
        )

        await message.reply_text(
            "Delete all cancelled."
        )

        return

    #
    # Rename requirement
    #
    rename_ticket_id = context.user_data.get(
        "rename_ticket_id"
    )

    if rename_ticket_id:
        new_name = update.message.text.strip()

        context.user_data.pop(
            "rename_ticket_id",
            None
        )

        result = rename_requirement(
            rename_ticket_id,
            new_name
        )

        await message.reply_text(
            result.message
        )

        return

    #
    # Add text to requirement
    #
    add_text_ticket_id = context.user_data.get(
        "add_text_ticket_id"
    )

    if add_text_ticket_id:
        text = update.message.text.strip()

        context.user_data.pop(
            "add_text_ticket_id",
            None
        )

        result = add_requirement_text(
            add_text_ticket_id,
            text
        )

        await message.reply_text(
            result.message
        )

        return

    #
    # Comment-based test case improvement
    #
    comment_testcase_ticket_id = context.user_data.get(
        "comment_testcase_ticket_id"
    )

    if comment_testcase_ticket_id:
        logger.warning(
            "TESTCASE COMMENT FLOW ACTIVATED. ticket_id=%s",
            comment_testcase_ticket_id,
        )

        comment_text = update.message.text.strip()

        context.user_data.pop(
            "comment_testcase_ticket_id",
            None,
        )

        await message.reply_text(
            f"Received your test case improvement comment.\n\n"
            f"Requirement: {comment_testcase_ticket_id}\n"
            f"Improving test cases now..."
        )

        try:
            result = run_comment_improve_testcases(
                ticket_id=comment_testcase_ticket_id,
                comment=comment_text,
            )

            version = result.get("version", "improved")

            testcases = (
                result.get("improved_testcases")
                or result.get("testcases")
                or []
            )

            excel_file = export_generated_testcases_excel(
                ticket_id=comment_testcase_ticket_id,
                result=result,
                version=version,
            )

            await send_excel_file_from_message(
                message,
                comment_testcase_ticket_id,
                excel_file,
                caption=f"Improved testcases Excel file: {comment_testcase_ticket_id}",
            )

            await message.reply_text(
                f"✅ Test cases improved: {comment_testcase_ticket_id}\n\n"
                f"Version: {version}\n"
                f"Testcases: {len(testcases)}\n\n"
                f"Choose next action:",
                reply_markup=build_review_keyboard(
                    comment_testcase_ticket_id
                ),
            )

        except Exception as error:
            logger.exception(
                "Failed to improve test cases by comment. ticket_id=%s",
                comment_testcase_ticket_id,
            )

            await message.reply_text(
                f"Failed to improve test cases:\n{error}"
            )

        return

    #
    # Clarification answers
    #
    ticket_id = context.user_data.get(
        "answering_clarifications_for"
    )

    if not ticket_id:
        return

    answer_text = update.message.text

    save_clarification_answers(
        ticket_id,
        answer_text
    )

    apply_clarification_answers_to_requirement(
        ticket_id
    )

    next_action = context.user_data.get(
        "clarification_next_action",
        "generate"
    )

    context.user_data.pop(
        "answering_clarifications_for",
        None
    )

    context.user_data.pop(
        "clarification_next_action",
        None
    )

    await message.reply_text(
        f"Clarification answers saved for {ticket_id}.\n"
        f"Generating requirement summary..."
    )

    if next_action == "analyze":
        await run_requirement_summary(ticket_id)
        await export_requirement_intelligence(
            message,
            ticket_id,
        )
        return

    await continue_generation_with_structure_gate(
        message,
        ticket_id,
    )


async def handle_review_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    
    query = update.callback_query

    await query.answer()

    data = query.data

    handled = await handle_structure_callback(
        update,
        context,
        after_approve_callback=continue_generation_with_structure_gate,
    )

    if handled:
        return

    parts = query.data.split(":")

    if len(parts) < 2:
        await query.message.reply_text(
            "Invalid action."
        )
        return

    action = parts[0]

    if data.startswith("testcase_ai_review:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        await query.message.reply_text(
            f"Running AI test case review for {ticket_id}..."
        )

        try:
            result = run_testcase_ai_review(ticket_id)
            review = result.get("coverage_review", {})

            summary_text = render_testcase_review_chat_summary(
                ticket_id=ticket_id,
                review=review,
            )

            await query.message.reply_text(summary_text)

            excel_file = export_generated_testcases_excel(
                ticket_id=ticket_id,
                result=result,
                version="review",
            )

            await send_excel_file_from_message(
                query.message,
                ticket_id,
                excel_file,
                caption=f"Reviewed testcases Excel file: {ticket_id}",
            )

            await query.message.reply_text(
                "Choose next action:",
                reply_markup=build_review_keyboard(ticket_id),
            )

        except Exception as error:
            await query.message.reply_text(
                f"Failed to review test cases:\n{error}"
            )

        return
    
    if data.startswith("testcase_comment:"):
        await query.answer()
        ticket_id = data.split(":")[1]

        context.user_data["comment_testcase_ticket_id"] = ticket_id

        await query.message.reply_text(
            "Please enter your test case improvement comment."
        )

        return
    
    if data.startswith("testcase_accept:"):
        await query.answer()

        ticket_id = data.split(":")[1]

        try:
            mark_accepted(ticket_id)

            await query.message.reply_text(
                f"✅ Test cases accepted for {ticket_id}."
            )

        except Exception as error:
            await query.message.reply_text(
                f"Failed to accept test cases:\n{error}"
            )

        return

    if action in [
        "answer_clarifications",
        "skip_clarifications"
    ]:
        if len(parts) < 3:
            await query.message.reply_text(
                "Invalid clarification action."
            )
            return

        mode = parts[1]
        ticket_id = parts[2]

        if action == "answer_clarifications":
            context.user_data[
                "answering_clarifications_for"
            ] = ticket_id

            context.user_data[
                "clarification_next_action"
            ] = mode

            await query.message.reply_text(
                "Please reply with clarification answers in this format:\n\n"
                "Q001: answer...\n"
                "Q002: answer...\n\n"
                "After receiving your answers, I will continue the workflow."
            )

            return

        if action == "skip_clarifications":
            await query.edit_message_text(
                f"⏭️ Clarifications skipped for {ticket_id}.\n\n"
                f"Generating requirement summary..."
            )

            if mode == "analyze":
                await run_requirement_summary(ticket_id)
                await export_requirement_intelligence(
                    query.message,
                    ticket_id,
                )
                return

            await continue_generation_with_structure_gate(
                query.message,
                ticket_id,
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

    if action == "comment_improve":
        if not can_improve_again(ticket_id):
            await query.edit_message_text(
                f"⚠️ Maximum improvement iterations reached for {ticket_id}.\n\n"
                f"Please review manually or accept the current version."
            )
            return

        context.user_data[
            "comment_improve_for"
        ] = ticket_id

        await query.message.reply_text(
            "Please describe what you want AI to improve.\n\n"
            "Examples:\n"
            "- Add more negative test cases\n"
            "- Add boundary value test cases\n"
            "- Add API validation scenarios\n"
            "- Add security test cases\n"
            "- Focus on duplicate email and concurrency cases"
        )

        return

    if action == "accept":
        mark_accepted(
            ticket_id
        )

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

        session = increment_improve_iteration(
            ticket_id
        )

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

        save_improvement_history_item(
            ticket_id=ticket_id,
            version=version,
            iteration=session.get("improve_iterations", 0),
            coverage_score=final_review.get("coverage_score", ""),
            improvement_score=final_review.get("improvement_score", ""),
            note="AI improve again"
        )

        improve_message = (
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
                improve_message += f"- {item}\n"
        else:
            improve_message += "- None\n"

        if can_improve_again(ticket_id):
            improve_message += (
                "\nDo you want AI to improve test cases again?"
            )
        else:
            improve_message += (
                "\nMaximum improvement iterations reached."
            )

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=improve_message,
            reply_markup=build_review_keyboard(ticket_id)
        )

        excel_file = export_generated_testcases_excel(
            ticket_id=ticket_id,
            result=result,
            version=version,
        )

        await send_excel_file_to_chat(
            context,
            query.message.chat_id,
            ticket_id,
            excel_file,
            caption=f"Generated testcases Excel file: {ticket_id}"
        )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage: /status <requirement_id>"
        )
        return

    raw_id = " ".join(context.args)

    ticket_id = resolve_requirement_id(
        raw_id
    )

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    result = get_requirement_status(
        ticket_id
    )

    message = get_message(update)

    await message.reply_text(
        result.message
    )
    
async def requirements(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    result = list_requirement_items()

    message = get_message(update)

    await message.reply_text(
        result.message
    )
    

async def rename(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if len(context.args) < 2:
        message = get_message(update)

        await message.reply_text(
            "Usage: /rename <requirement_id> <new summary>"
        )
        return

    raw_id = context.args[0]

    ticket_id = resolve_requirement_id(
        raw_id
    )

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    new_summary = " ".join(
        context.args[1:]
    ).strip()

    result = rename_requirement(
        ticket_id,
        new_summary
    )

    message = get_message(update)

    await message.reply_text(
        result.message
    )


async def delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        message = get_message(update)

        await message.reply_text(
            "Usage: /delete <requirement_id>"
        )
        return

    raw_id = " ".join(context.args)

    ticket_id = resolve_requirement_id(
        raw_id
    )

    if not ticket_id:
        message = get_message(update)

        await message.reply_text(
            f"Requirement not found: {raw_id}"
        )
        return

    result = delete_requirement(
        ticket_id
    )

    message = get_message(update)

    await message.reply_text(
        result.message
    )
    

async def delete_all(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data[
        "confirm_delete_all"
    ] = True

    message = get_message(update)

    await message.reply_text(
        "⚠️ WARNING\n\n"
        "This will delete ALL requirements.\n\n"
        "Please Enter DELETE ALL PASSWORD"
    )


async def analyze_jira(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = get_message(update)

    if not context.args:
        await message.reply_text(
            "Usage:\n/analyze_jira <jira_ticket_number>"
        )
        return

    issue_key = " ".join(context.args).strip()

    await message.reply_text(
        f"Creating requirement from Jira ticket {issue_key}..."
    )

    try:
        ticket_id = create_requirement_from_jira(issue_key)

        await message.reply_text(
            f"Requirement created from Jira.\n"
            f"Requirement ID: {ticket_id}\n\n"
            f"Analyzing requirement..."
        )

        await analyze_existing_ticket(
            message,
            context,
            ticket_id,
        )

    except Exception as error:
        logger.exception(
            "Failed to analyze Jira ticket. issue_key=%s",
            issue_key,
        )

        await message.reply_text(
            f"Failed to analyze Jira ticket:\n{error}"
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
        .connect_timeout(30)
        .read_timeout(180)
        .write_timeout(180)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )
    
    app.add_handler(
        CommandHandler(
            "add_text",
            add_text
        )
    )

    app.add_handler(
        CommandHandler(
            "add_file",
            add_file
        )
    )

    app.add_handler(
        CommandHandler("analyze", analyze)
    )
    
    app.add_handler(
        CommandHandler(
            "analyze_text",
            analyze_text
        )
    )

    app.add_handler(
        CommandHandler(
            "analyze_jira",
            analyze_jira,
        )
    )

    app.add_handler(
        CommandHandler(
            "structure",
            structure
        )
    )

    app.add_handler(
        CommandHandler(
            "self_review_structure",
            self_review_structure
        )
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
        CommandHandler(
            "rename",
            rename
        )
    )
    
    app.add_handler(
        CommandHandler(
            "delete",
            delete
        )
    )

    app.add_handler(
        CommandHandler(
            "delete_all",
            delete_all
        )
    )
    
    app.add_handler(
        CommandHandler(
            "requirements",
            requirements
        )
    )
    
    app.add_handler(
        CommandHandler(
            "report",
            report
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_requirement_file
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            handle_review_action
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()