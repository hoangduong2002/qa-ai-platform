from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_reference_review.models import JiraStatement


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def load_jira_statements(ticket_id: str) -> list[JiraStatement]:
    root = Path("requirements") / ticket_id
    source_dir = root / "source"
    analysis_dir = root / "analysis"

    statements: list[JiraStatement] = []

    description = _read_text(source_dir / "description.md")
    if description:
        statements.append(
            JiraStatement(
                statement_id="JIRA-DESCRIPTION-1",
                source="source/description.md",
                text=description,
            )
        )

    comments = _read_text(source_dir / "comments.md")
    if comments:
        statements.append(
            JiraStatement(
                statement_id="JIRA-COMMENTS-1",
                source="source/comments.md",
                text=comments,
            )
        )

    answers = _read_json(analysis_dir / "clarification_answers.json") or {}
    clarified = answers.get("answered_clarifications", []) if isinstance(answers, dict) else []
    if isinstance(clarified, list):
        for index, item in enumerate(clarified, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("final_answer") or item.get("answer") or "").strip()
            if not text:
                continue
            statements.append(
                JiraStatement(
                    statement_id=f"JIRA-CLARIFICATION-{index}",
                    source="analysis/clarification_answers.json",
                    text=text,
                )
            )

    return statements
