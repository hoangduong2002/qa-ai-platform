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
import os


NON_PORTAL_AI_MODE_ENV = "NON_PORTAL_AI_MODE"


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
    state = {
        "ticket_id": ticket_id,
    }
    ai_mode = _resolve_ai_mode(ai_mode)

    if ai_mode:
        state["ai_mode"] = ai_mode
    if source_channel:
        state["source_channel"] = source_channel

    requirement_summary_graph.invoke(state)

    return load_ticket_artifacts(ticket_id)


async def run_requirement_questions(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
):
    state = {
        "ticket_id": ticket_id,
    }
    ai_mode = _resolve_ai_mode(ai_mode)

    if ai_mode:
        state["ai_mode"] = ai_mode
    if source_channel:
        state["source_channel"] = source_channel

    result = requirement_question_graph.invoke(state)

    save_clarification_questions_snapshot(
        ticket_id,
        result.get("clarifications", {})
    )

    return result


async def run_incremental_requirement_questions(
    ticket_id: str
):
    return run_incremental_requirement_analysis(
        ticket_id=ticket_id,
        ai_mode=_current_ai_mode(),
    )


async def run_incremental_scenarios(
    ticket_id: str
):
    return run_incremental_scenario_generation(
        ticket_id=ticket_id,
        ai_mode=_current_ai_mode(),
    )


async def run_incremental_testcases(
    ticket_id: str
):
    return run_incremental_testcase_generation(
        ticket_id=ticket_id,
        ai_mode=_current_ai_mode(),
    )
