import ast
import re
from pathlib import Path


BOT_FILE = Path("bot/telegram_bot.py")
WORKFLOW_FILE = Path("app/services/requirement_workflow_service.py")
GENERATION_FILE = Path("app/application/generation_orchestrator.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                return ast.get_source_segment(source, node) or ""

    raise AssertionError(f"Function not found: {function_name}")


def test_all_expected_command_handlers_are_registered():
    source = _source(BOT_FILE)
    compact_source = re.sub(r"\s+", "", source)

    for command in [
        "start",
        "add_text",
        "add_file",
        "analyze",
        "analyze_text",
        "analyze_jira",
        "generate",
        "generate_jira",
        "generate_text",
        "structure",
        "self_review_structure",
        "status",
        "rename",
        "delete",
        "delete_all",
        "requirements",
        "report",
    ]:
        assert f'CommandHandler("{command}"' in compact_source


def test_generate_text_can_create_requirement_state():
    generate_text_source = _function_source(BOT_FILE, "generate_text")

    assert "create_requirement_from_text" in generate_text_source
    assert 'source="telegram_generate_text"' in generate_text_source
    assert "process_ticket" in generate_text_source


def test_requirement_questions_and_summary_receive_ai_mode():
    bot_source = _source(BOT_FILE)
    workflow_source = _source(WORKFLOW_FILE)

    assert "TELEGRAM_AI_MODE" in bot_source
    assert "TELEGRAM_DEFAULT_AI_MODE = AI_MODE_PRODUCTION_HYBRID" in bot_source
    assert "run_requirement_questions(" in bot_source
    assert "ai_mode=ai_mode" in bot_source

    questions_signature = _function_source(
        WORKFLOW_FILE,
        "run_requirement_questions",
    )
    summary_signature = _function_source(
        WORKFLOW_FILE,
        "run_requirement_summary",
    )

    assert "ai_mode: str | None = None" in questions_signature
    assert "ai_mode: str | None = None" in summary_signature


def test_generation_state_includes_ai_mode():
    bot_source = _source(BOT_FILE)
    generation_source = _source(GENERATION_FILE)

    assert "build_structured_generation_state(" in bot_source
    assert "ai_mode=ai_mode" in bot_source
    assert 'artifacts["ai_mode"] = ai_mode' in generation_source
    assert 'generation_state["ai_mode"] = ai_mode' in bot_source


def test_generate_has_jira_fallback_behavior():
    generate_source = _function_source(BOT_FILE, "generate")
    generate_jira_source = _function_source(BOT_FILE, "generate_jira")

    assert "is_jira_issue_key(raw_id)" in generate_source
    assert "Requirement not found locally. Creating from Jira first..." in generate_source
    assert "create_requirement_from_jira(raw_id)" in generate_source
    assert "process_ticket(update, ticket_id)" in generate_source

    assert "create_requirement_from_jira(issue_key)" in generate_jira_source
    assert "process_ticket(update, ticket_id)" in generate_jira_source


def test_document_and_photo_handlers_exist():
    source = _source(BOT_FILE)

    assert "filters.Document.ALL" in source
    assert "handle_requirement_file" in source
    assert "filters.PHOTO" in source
    assert "handle_requirement_photo" in source
