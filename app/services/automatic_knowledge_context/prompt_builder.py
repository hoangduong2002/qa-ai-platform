from __future__ import annotations

from app.services.automatic_knowledge_context.models import KnowledgeRetrievalSnapshot


_HEADINGS = {
    "authoritative": "AUTHORITATIVE KNOWLEDGE",
    "supporting": "SUPPORTING TECHNICAL KNOWLEDGE",
    "historical": "PREVIOUS DEFECTS AND HISTORICAL EVIDENCE",
    "guideline": "PROJECT GUIDELINES",
}


def build_knowledge_prompt_context(snapshot: KnowledgeRetrievalSnapshot) -> str:
    """Render only selected snapshot references into bounded prompt context."""
    selected = [item for item in snapshot.references if item.used_in_prompt]
    if not selected:
        return "No Knowledge Base references were included for this Analysis run."

    lines = [
        f"Knowledge Snapshot: {snapshot.snapshot_id}",
        f"Jira Project: {snapshot.jira_project_key or 'N/A'}",
        f"Knowledge Base: {snapshot.knowledge_base_id or 'N/A'}",
        "",
    ]
    for authority in ("authoritative", "supporting", "historical", "guideline"):
        group = [item for item in selected if item.authority == authority]
        if not group:
            continue
        lines.extend([_HEADINGS[authority], ""])
        for item in group:
            lines.extend(
                [
                    f"[{item.reference_id}]",
                    f"Source: {item.title}",
                    f"Collection: {item.collection_id}",
                    f"Citation: {item.citation}",
                    "Content:",
                    item.excerpt,
                    "",
                ]
            )
    lines.extend(
        [
            "KNOWLEDGE USE INSTRUCTIONS",
            "- Jira Requirement text and current authoritative business rules have highest authority.",
            "- Existing test cases are prior-coverage evidence, not proof of current behavior.",
            "- Previous defects are historical evidence, not current specifications.",
            "- Project guidelines guide analysis structure and do not override product rules.",
            "- Cite the stable [REF-xxx] label when a conclusion depends on Knowledge.",
            "- Explicitly report conflicts between Jira and Knowledge or between authoritative sources.",
            "- Do not invent rules or silently choose between conflicting authoritative sources.",
        ]
    )
    return "\n".join(lines)
