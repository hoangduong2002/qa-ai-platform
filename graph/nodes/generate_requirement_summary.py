import json
from pathlib import Path

from app.services.llm_service import get_llm


def _read_text(
    file_path: Path,
) -> str:
    if not file_path.exists():
        return ""

    return file_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )


def _read_json(
    file_path: Path,
):
    if not file_path.exists():
        return None

    try:
        return json.loads(
            file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        )
    except Exception:
        return None


def _normalize_clarification_answers(
    clarification_answers,
) -> list[dict]:
    """
    Support both formats:

    1. List format:
       [
         {
           "question_id": "Q001",
           "question": "...",
           "answer": "..."
         }
       ]

    2. Dict format:
       {
         "answers": [...]
       }

    3. Dict format:
       {
         "clarification_answers": [...]
       }
    """

    if not clarification_answers:
        return []

    if isinstance(clarification_answers, list):
        return clarification_answers

    if isinstance(clarification_answers, dict):
        if isinstance(
            clarification_answers.get("answers"),
            list,
        ):
            return clarification_answers["answers"]

        if isinstance(
            clarification_answers.get("clarification_answers"),
            list,
        ):
            return clarification_answers["clarification_answers"]

        if isinstance(
            clarification_answers.get("items"),
            list,
        ):
            return clarification_answers["items"]

    return []


def _build_clarification_answer_context(
    answer_items: list[dict],
) -> str:
    if not answer_items:
        return "No clarification answers provided."

    lines = []

    for item in answer_items:
        question_id = (
            item.get("question_id")
            or item.get("id")
            or "N/A"
        )

        question = (
            item.get("question")
            or item.get("text")
            or item.get("description")
            or ""
        )

        answer = (
            item.get("answer")
            or item.get("response")
            or ""
        )

        if not answer:
            continue

        lines.extend(
            [
                f"Question ID: {question_id}",
                f"Question: {question}",
                f"Answer: {answer}",
                "",
            ]
        )

    if not lines:
        return "No clarification answers provided."

    return "\n".join(lines).strip()


def generate_requirement_summary(
    state: dict,
) -> dict:
    ticket_id = state["ticket_id"]

    base_dir = Path("requirements") / ticket_id
    analysis_dir = base_dir / "analysis"
    source_dir = base_dir / "source"

    sanitized_requirement_file = (
        analysis_dir / "sanitized_requirement.md"
    )

    requirement_analysis_file = (
        analysis_dir / "requirement_analysis.json"
    )

    requirement_items_file = (
        analysis_dir / "requirement_items.json"
    )

    clarification_answers_file = (
        analysis_dir / "clarification_answers.json"
    )

    output_file = (
        analysis_dir / "requirement_summary.json"
    )

    requirement_context = _read_text(
        sanitized_requirement_file
    )

    if not requirement_context:
        requirement_context = _read_text(
            source_dir / "description.md"
        )

    requirement_analysis = _read_json(
        requirement_analysis_file
    )

    requirement_items = _read_json(
        requirement_items_file
    )

    clarification_answers_raw = _read_json(
        clarification_answers_file
    )

    clarification_answer_items = (
        _normalize_clarification_answers(
            clarification_answers_raw
        )
    )

    clarification_answer_context = (
        _build_clarification_answer_context(
            clarification_answer_items
        )
    )

    llm = get_llm()

    prompt = f"""
You are a senior QA analyst.

Create a structured requirement summary from the requirement context, analysis output, requirement items, and clarification answers.

The summary must be useful for generating test scenarios and test cases.

Return JSON only.

Required JSON format:
{{
  "overview": "",
  "functional_requirements": [
    {{
      "id": "FR001",
      "description": "",
      "priority": "High"
    }}
  ],
  "business_rules": [
    {{
      "id": "BR001",
      "description": "",
      "priority": "High"
    }}
  ],
  "validations": [
    {{
      "id": "VAL001",
      "description": "",
      "priority": "Medium"
    }}
  ],
  "integrations": [
    {{
      "id": "INT001",
      "description": "",
      "priority": "Medium"
    }}
  ],
  "error_handling": [
    {{
      "id": "ERR001",
      "description": "",
      "priority": "Medium"
    }}
  ],
  "non_functional_requirements": [
    {{
      "id": "NFR001",
      "description": "",
      "priority": "Low"
    }}
  ],
  "assumptions": [],
  "out_of_scope": [],
  "open_questions": []
}}

Requirement Context:
{requirement_context}

Requirement Analysis:
{json.dumps(requirement_analysis, indent=2, ensure_ascii=False)}

Requirement Items:
{json.dumps(requirement_items, indent=2, ensure_ascii=False)}

Clarification Answers:
{clarification_answer_context}
"""

    response = llm.invoke(prompt)

    content = (
        response.content
        if hasattr(response, "content")
        else str(response)
    )

    content = content.strip()

    if content.startswith("```json"):
        content = content.replace("```json", "", 1).strip()

    if content.startswith("```"):
        content = content.replace("```", "", 1).strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    try:
        summary = json.loads(content)
    except Exception:
        summary = {
            "overview": content,
            "functional_requirements": [],
            "business_rules": [],
            "validations": [],
            "integrations": [],
            "error_handling": [],
            "non_functional_requirements": [],
            "assumptions": [],
            "out_of_scope": [],
            "open_questions": [],
        }

    analysis_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {
        "requirement_summary": summary,
    }