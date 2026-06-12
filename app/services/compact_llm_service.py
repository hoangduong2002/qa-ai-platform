import time

from app.services.llm_router_service import (
    TASK_COMPACT_CONTEXT,
    LLMRouterResponse,
    call_text_llm,
    resolve_provider_for_task,
)
from app.services.portal_ai_mode_service import (
    PRODUCTION_HYBRID,
    get_current_portal_ai_mode,
)


COMPACT_SYSTEM_PROMPT = """
You are a QA requirement compression assistant.
Convert noisy Jira/Figma evidence into concise, traceable QA context.
Preserve explicit business rules, validations, user actions, visible UI text,
screen names, open questions, and source traceability. Do not invent facts.
Return Markdown only.
""".strip()


def _current_ai_mode() -> str:
    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode and portal_ai_mode.get("ai_mode"):
        return str(portal_ai_mode["ai_mode"]).strip().upper()

    return PRODUCTION_HYBRID


def _call_compact_llm(prompt: str) -> LLMRouterResponse:
    ai_mode = _current_ai_mode()
    resolution = resolve_provider_for_task(TASK_COMPACT_CONTEXT, ai_mode)
    started = time.time()
    content = call_text_llm(
        TASK_COMPACT_CONTEXT,
        prompt,
        system_prompt=COMPACT_SYSTEM_PROMPT,
        ai_mode=ai_mode,
    )
    duration = time.time() - started

    return LLMRouterResponse(
        content=content,
        provider=resolution.get("provider", ""),
        model=resolution.get("model", ""),
        fallback_used=False,
        duration_seconds=duration,
        input_chars=len(prompt or "") + len(COMPACT_SYSTEM_PROMPT),
        output_chars=len(content or ""),
        raw={"ai_mode": ai_mode, "reason": resolution.get("reason", "")},
    )


def compact_chunk_with_llm(
    chunk_type: str,
    chunk_text: str,
) -> LLMRouterResponse:
    prompt = f"""
Summarize this requirement evidence chunk for downstream QA test design.

Chunk type: {chunk_type}

Return Markdown with these sections when relevant:
- Summary
- Functional / Explicit Requirement Signals
- UI / Screen Signals
- Possible Actions
- Validation / Business Rules
- Open Questions
- Source Traceability

Evidence:
{chunk_text}
""".strip()

    return _call_compact_llm(prompt)


def merge_compact_context_with_llm(
    ticket_id: str,
    compact_context: str,
) -> LLMRouterResponse:
    prompt = f"""
Create the final compact requirement context for ticket {ticket_id}.

Deduplicate repeated points and keep the output concise, but preserve:
- ticket summary
- functional requirements
- Figma sections and screens
- key visible texts/states
- possible actions
- validation/business rules
- open questions
- traceability summary

Draft context:
{compact_context}
""".strip()

    return _call_compact_llm(prompt)
