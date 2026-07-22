from __future__ import annotations

import json

from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm
from app.services.knowledge_reference_review.config import llm_conflict_assist_enabled


_PROMPT = """
You are assisting conflict discovery between Jira and Knowledge Base excerpts.
Return JSON only:
{
  "possible_conflicts": [
    {
      "source_result_id": "",
      "rationale": "",
      "human_confirmation_required": true
    }
  ]
}
Do not resolve conflicts automatically.
""".strip()


def detect_possible_conflicts_with_llm(*, ai_mode: str | None, jira_statements: list[dict], candidate: dict) -> list[dict]:
    if not llm_conflict_assist_enabled():
        return []

    payload = {
        "jira_statements": jira_statements,
        "candidate_reference": candidate,
    }

    response = call_text_llm(
        task_type=TASK_REQUIREMENT_ANALYSIS,
        prompt=_PROMPT + "\n\nInput:\n" + json.dumps(payload, indent=2, ensure_ascii=False),
        ai_mode=ai_mode,
    )

    try:
        parsed = json.loads(response)
    except Exception:
        return []

    if not isinstance(parsed, dict):
        return []

    value = parsed.get("possible_conflicts", [])
    return value if isinstance(value, list) else []
