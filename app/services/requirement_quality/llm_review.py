from __future__ import annotations

import json

from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm
from app.services.requirement_quality.config import llm_review_enabled


REVIEW_PROMPT = """
You review a deterministic requirement quality report and may suggest additional WARNING-level quality issues.
Return strict JSON object only:
{
  "additional_warnings": [
    {
      "affected_field": "",
      "explanation": "",
      "evidence": [""],
      "proposed_question": "",
      "kb_retrieval_could_help": false,
      "human_confirmation_mandatory": true
    }
  ]
}

Do not invent unsupported business facts.
Do not use knowledge base content.
""".strip()


def review_quality_with_llm(*, ai_mode: str | None, structured_analysis: dict, deterministic_report: dict) -> dict:
    if not llm_review_enabled():
        return {"additional_warnings": []}

    payload = {
        "structured_analysis": structured_analysis,
        "deterministic_report": deterministic_report,
    }

    prompt = REVIEW_PROMPT + "\n\nInput:\n" + json.dumps(payload, indent=2, ensure_ascii=False)

    content = call_text_llm(
        task_type=TASK_REQUIREMENT_ANALYSIS,
        prompt=prompt,
        ai_mode=ai_mode,
    )

    try:
        parsed = json.loads(content)
    except Exception:
        return {"additional_warnings": []}

    if not isinstance(parsed, dict):
        return {"additional_warnings": []}

    warnings = parsed.get("additional_warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    return {"additional_warnings": warnings}
