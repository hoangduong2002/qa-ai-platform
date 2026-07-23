from graph.requirement_question_graph import (
    requirement_question_graph
)
from graph.requirement_summary_graph import (
    requirement_summary_graph
)
from app.utils.artifact_loader import (
    load_ticket_artifacts
)
from app.utils.clarification_session import (
    save_clarification_questions_snapshot
)
from app.services.portal_ai_mode_service import (
    get_current_portal_ai_mode,
)
from app.services.incremental_requirement_analysis_service import (
    run_incremental_requirement_analysis,
)
from app.services.incremental_generation_service import (
    run_incremental_scenario_generation,
    run_incremental_testcase_generation,
)
from app.services.automatic_knowledge_context.artifacts import (
    create_analysis_run_id,
    save_analysis_run,
)
from app.services.automatic_knowledge_context.service import prepare_knowledge_context
from app.services.web_requirement_service import create_requirement_from_jira_and_sanitize
from graph.nodes.load_requirement import load_requirement
import os
import logging


NON_PORTAL_AI_MODE_ENV = "NON_PORTAL_AI_MODE"
logger = logging.getLogger(__name__)


def _prepare_analysis_state(
    *,
    ticket_id: str,
    ai_mode: str | None,
    source_channel: str | None,
    use_reviewed_references: bool = False,
    adjusted_by: str = "",
) -> tuple[dict, str, str]:
    state = {"ticket_id": ticket_id}
    if ai_mode:
        state["ai_mode"] = ai_mode
    if source_channel:
        state["source_channel"] = source_channel
    state.update(load_requirement(state))
    analysis_run_id = create_analysis_run_id()
    snapshot, prompt_context = prepare_knowledge_context(
        ticket_id=ticket_id,
        analysis_run_id=analysis_run_id,
        requirement_context=state.get("requirement_context", ""),
        use_reviewed_references=use_reviewed_references,
        adjusted_by=adjusted_by,
    )
    state.update(
        {
            "analysis_run_id": analysis_run_id,
            "jira_issue_key": snapshot.jira_issue_key,
            "jira_project_key": snapshot.jira_project_key,
            "knowledge_base_id": snapshot.knowledge_base_id,
            "knowledge_snapshot_id": snapshot.snapshot_id,
            "knowledge_retrieval_status": snapshot.status.value,
            "knowledge_context": prompt_context,
            "knowledge_references": [
                {
                    "reference_id": item.reference_id,
                    "source_result_id": item.source_result_id,
                    "collection_id": item.collection_id,
                    "document_id": item.document_id,
                    "document_version": item.document_version,
                    "chunk_index": item.chunk_index,
                    "authority": item.authority,
                    "selected": item.selected,
                    "used_in_prompt": item.used_in_prompt,
                }
                for item in snapshot.references
            ],
            "knowledge_warnings": snapshot.warnings,
        }
    )
    return state, analysis_run_id, snapshot.snapshot_id


def _invoke_analysis_graph(
    *,
    graph,
    ticket_id: str,
    ai_mode: str | None,
    source_channel: str | None,
    use_reviewed_references: bool = False,
    adjusted_by: str = "",
) -> dict:
    state, analysis_run_id, snapshot_id = _prepare_analysis_state(
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
        use_reviewed_references=use_reviewed_references,
        adjusted_by=adjusted_by,
    )
    logger.info(
        "requirement_analysis_started ticket_id=%s analysis_run_id=%s snapshot_id=%s",
        ticket_id,
        analysis_run_id,
        snapshot_id,
    )
    try:
        result = graph.invoke(state)
        save_analysis_run(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            snapshot_id=snapshot_id,
            status="completed",
        )
        logger.info(
            "requirement_analysis_completed ticket_id=%s analysis_run_id=%s snapshot_id=%s",
            ticket_id,
            analysis_run_id,
            snapshot_id,
        )
        return result
    except Exception:
        save_analysis_run(
            ticket_id=ticket_id,
            analysis_run_id=analysis_run_id,
            snapshot_id=snapshot_id,
            status="failed",
            error="Requirement Analysis failed.",
        )
        raise


def _run_requirement_questions_sync(
    *,
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
    use_reviewed_references: bool = False,
    adjusted_by: str = "",
) -> dict:
    result = _invoke_analysis_graph(
        graph=requirement_question_graph,
        ticket_id=ticket_id,
        ai_mode=_resolve_ai_mode(ai_mode),
        source_channel=source_channel,
        use_reviewed_references=use_reviewed_references,
        adjusted_by=adjusted_by,
    )
    save_clarification_questions_snapshot(
        ticket_id,
        result.get("clarifications", {}),
    )
    return result


def _current_ai_mode() -> str | None:
    mode = get_current_portal_ai_mode()

    if not mode:
        return None

    return mode.get("ai_mode")


def _resolve_ai_mode(ai_mode: str | None = None) -> str | None:
    if ai_mode:
        return ai_mode

    portal_ai_mode = _current_ai_mode()

    if portal_ai_mode:
        return portal_ai_mode

    return os.getenv(NON_PORTAL_AI_MODE_ENV, "").strip().upper() or None


async def run_requirement_summary(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    ai_mode = _resolve_ai_mode(ai_mode)
    _invoke_analysis_graph(
        graph=requirement_summary_graph,
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )

    return load_ticket_artifacts(ticket_id)


async def run_requirement_questions(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
    use_reviewed_references: bool = False,
    adjusted_by: str = "",
):
    return _run_requirement_questions_sync(
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
        use_reviewed_references=use_reviewed_references,
        adjusted_by=adjusted_by,
    )


def create_jira_requirement_and_run_analysis(
    *,
    issue_key: str,
    jira_pat: str = "",
    refresh_existing: bool = False,
    load_subtasks: bool | None = None,
    load_figma: bool | None = None,
    ai_mode: str | None = None,
    source_channel: str = "web",
) -> str:
    """Create a Jira Requirement and run automatic Knowledge-aware Analysis."""
    ticket_id = create_requirement_from_jira_and_sanitize(
        issue_key=issue_key,
        jira_pat=jira_pat,
        refresh_existing=refresh_existing,
        load_subtasks=load_subtasks,
        load_figma=load_figma,
    )
    _run_requirement_questions_sync(
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )
    return ticket_id


async def run_incremental_requirement_questions(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    return run_incremental_requirement_analysis(
        ticket_id=ticket_id,
        ai_mode=ai_mode or _current_ai_mode(),
        source_channel=source_channel,
    )


async def run_incremental_scenarios(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    return run_incremental_scenario_generation(
        ticket_id=ticket_id,
        ai_mode=ai_mode or _current_ai_mode(),
        source_channel=source_channel,
    )


async def run_incremental_testcases(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    return run_incremental_testcase_generation(
        ticket_id=ticket_id,
        ai_mode=ai_mode or _current_ai_mode(),
        source_channel=source_channel,
    )
