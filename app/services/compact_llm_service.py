from app.services.llm_router_service import LLMRouterResponse, call_llm_with_fallback


COMPACT_SYSTEM_PROMPT = """
You are a QA requirement compression assistant.
Convert noisy Jira/Figma evidence into concise, traceable QA context.
Preserve explicit business rules, validations, user actions, visible UI text,
screen names, open questions, and source traceability. Do not invent facts.
Return Markdown only.
""".strip()


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

    return call_llm_with_fallback(
        task_type="compact_context",
        prompt=prompt,
        system_prompt=COMPACT_SYSTEM_PROMPT,
    )


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

    return call_llm_with_fallback(
        task_type="compact_context",
        prompt=prompt,
        system_prompt=COMPACT_SYSTEM_PROMPT,
    )
