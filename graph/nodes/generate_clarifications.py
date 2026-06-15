import json
import os
from typing import Any

from app.services.llm_router_service import (
    TASK_CLARIFICATION_GENERATION,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.prompt_loader import load_prompt
from app.utils.file_writer import save_clarifications, save_raw_response
from app.utils.llm_json import parse_json
from app.utils.clarification_session import (
    load_clarification_answers,
    load_clarifications,
)
from app.utils.clarification_answers import normalize_clarification_answers


PRIORITY_ORDER = {
    "High": 0,
    "Medium": 1,
    "Low": 2,
}

VALID_IMPACTS = set(PRIORITY_ORDER.keys())


def _resolve_ai_mode(state: dict | None = None) -> str | None:
    state = state or {}

    if state.get("ai_mode"):
        return state.get("ai_mode")

    portal_ai_mode = get_current_portal_ai_mode()

    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def _assert_llm_json_candidate(content: str) -> None:
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            "Clarification generation LLM returned an empty response. Expected strict JSON."
        )

    stripped = content.strip()
    lowered = stripped.lower()

    blocked_markers = [
        "[skipped]",
        "[error]",
        "provider blocked",
        "call blocked",
        "no_llm",
        "requires llm",
    ]

    if any(marker in lowered for marker in blocked_markers):
        raise RuntimeError(
            "Clarification generation did not receive a valid LLM JSON response."
        )


def _normalize_suggested_options(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []

    options = []

    for index, option in enumerate(value, start=1):
        if not isinstance(option, dict):
            continue

        key = str(option.get("key") or "").strip().upper()
        label = str(option.get("label") or "").strip()
        assumption = str(option.get("assumption") or "").strip()

        if not label:
            continue

        if not key:
            key = chr(ord("A") + len(options))

        options.append(
            {
                "key": key,
                "label": label,
                "assumption": assumption,
            }
        )

    if not options:
        return []

    non_other_options = [
        option
        for option in options
        if "other" not in option["label"].lower()
    ]

    limited = [
        {
            **option,
            "key": chr(ord("A") + index),
        }
        for index, option in enumerate(non_other_options[:3])
    ]

    while len(limited) < 1:
        limited.append(
            {
                "key": chr(ord("A") + len(limited)),
                "label": "Needs clarification",
                "assumption": "",
            }
        )

    limited.append(
        {
            "key": chr(ord("A") + len(limited)),
            "label": "Other / custom answer",
            "assumption": "",
        }
    )

    return limited[:4]


def _get_max_clarifications_per_round() -> int:
    value = os.getenv("MAX_CLARIFICATIONS_PER_ROUND", "5")

    try:
        number = int(value)
    except ValueError:
        number = 5

    return max(number, 1)


def _get_max_clarification_rounds() -> int:
    value = os.getenv("MAX_CLARIFICATION_ROUNDS", "3")

    try:
        number = int(value)
    except ValueError:
        number = 3

    return max(number, 1)


def _normalize_clarifications(data: Any) -> dict:
    if isinstance(data, dict):
        questions = data.get("clarification_questions", [])

        if not isinstance(questions, list):
            questions = []

        data["clarification_questions"] = questions
        return data

    if isinstance(data, list):
        return {
            "clarification_questions": data,
        }

    return {
        "clarification_questions": [],
    }


def _as_list(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _normalize_question(
    question: dict,
    index: int,
) -> dict:
    item = dict(question)

    question_id = (
        item.get("question_id")
        or item.get("id")
        or f"Q{index:03d}"
    )

    item["id"] = question_id
    item["question_id"] = question_id

    item["question"] = (
        item.get("question")
        or item.get("question_text")
        or item.get("text")
        or item.get("description")
        or ""
    )

    priority = (
        item.get("priority")
        or item.get("impact")
        or "Medium"
    )

    if priority not in VALID_IMPACTS:
        priority = "Medium"

    item["priority"] = priority
    impact = item.get("impact") or priority

    if impact not in VALID_IMPACTS:
        impact = "Medium"

    item["impact"] = impact
    item["category"] = item.get("category") or "Other"
    item["reason"] = item.get("reason") or ""
    item["free_text_allowed"] = bool(
        item.get("free_text_allowed", True)
    )
    item["suggested_options"] = _normalize_suggested_options(
        item.get("suggested_options")
    )
    item["blocking"] = bool(
        item.get("blocking", priority == "High")
    )

    related_requirement_ids = item.get("related_requirement_ids", [])

    if isinstance(related_requirement_ids, str):
        related_requirement_ids = [
            requirement_id.strip()
            for requirement_id in related_requirement_ids.split(",")
            if requirement_id.strip()
        ]

    if not isinstance(related_requirement_ids, list):
        related_requirement_ids = []

    item["related_requirement_ids"] = related_requirement_ids

    return item


def _question_sort_key(question: dict) -> tuple:
    priority = question.get("priority") or question.get("impact") or "Medium"
    blocking = question.get("blocking", False)

    return (
        0 if blocking else 1,
        PRIORITY_ORDER.get(priority, 1),
        question.get("question_id", ""),
    )


def _answered_question_texts(
    answered_clarifications: list,
) -> set[str]:
    result = set()

    for item in answered_clarifications:
        if not isinstance(item, dict):
            continue

        question = item.get("question", "")

        if question:
            result.add(question.strip().lower())

    return result


def _answered_question_ids(
    answered_clarifications: list,
) -> set[str]:
    result = set()

    for item in answered_clarifications:
        if not isinstance(item, dict):
            continue

        question_id = item.get("question_id", "")

        if question_id:
            result.add(question_id.strip().upper())

    return result


def _filter_and_limit_questions(
    questions: list,
    answered_clarifications: list,
    max_questions: int,
) -> list:
    answered_ids = _answered_question_ids(answered_clarifications)
    answered_texts = _answered_question_texts(answered_clarifications)

    normalized_questions = []

    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue

        item = _normalize_question(question, index)

        question_id = item.get("question_id", "").strip().upper()
        question_text = item.get("question", "").strip().lower()

        if not question_text:
            continue

        if question_id in answered_ids:
            continue

        if question_text in answered_texts:
            continue

        normalized_questions.append(item)

    normalized_questions.sort(key=_question_sort_key)

    limited_questions = normalized_questions[:max_questions]

    for index, question in enumerate(limited_questions, start=1):
        question["question_id"] = f"Q{index:03d}"
        question["id"] = question["question_id"]

    return limited_questions


def _get_current_round(previous_clarifications: dict) -> int:
    if not isinstance(previous_clarifications, dict):
        return 0

    value = (
        previous_clarifications.get("clarification_round")
        or previous_clarifications.get("round")
        or 0
    )

    try:
        return int(value)
    except ValueError:
        return 0


def generate_clarifications(state):
    ticket_id = state["ticket_id"]
    ai_mode = _resolve_ai_mode(state)

    max_questions = _get_max_clarifications_per_round()
    max_rounds = _get_max_clarification_rounds()

    clarification_answers = load_clarification_answers(ticket_id)
    answered_clarifications = normalize_clarification_answers(
        clarification_answers
    )

    previous_clarifications = load_clarifications(ticket_id)
    current_round = _get_current_round(previous_clarifications)

    if current_round >= max_rounds:
        clarifications = {
            "clarification_round": current_round,
            "max_clarification_rounds": max_rounds,
            "max_clarifications_per_round": max_questions,
            "clarification_status": "MAX_ROUNDS_REACHED",
            "clarification_questions": [],
            "answered_clarifications_count": len(answered_clarifications),
            "message": (
                "Maximum clarification rounds reached. "
                "Remaining uncertainties should be handled as assumptions, "
                "open questions, or risks."
            ),
        }

        save_clarifications(ticket_id, clarifications)

        return {
            "clarifications": clarifications,
        }

    next_round = current_round + 1

    prompt = load_prompt("prompts/generate_clarifications.md")

    final_prompt = (
        prompt
        .replace(
            "{analysis}",
            json.dumps(
                state.get("analysis", {}),
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{answered_clarifications}",
            json.dumps(
                answered_clarifications,
                indent=2,
                ensure_ascii=False,
            ),
        )
        .replace(
            "{max_clarifications_per_round}",
            str(max_questions),
        )
        .replace(
            "{max_clarification_rounds}",
            str(max_rounds),
        )
        .replace(
            "{current_clarification_round}",
            str(next_round),
        )
    )

    try:
        raw_response = call_text_llm(
            task_type=TASK_CLARIFICATION_GENERATION,
            prompt=final_prompt,
            ai_mode=ai_mode,
        )
    except Exception as error:
        save_raw_response(
            ticket_id,
            "generate_clarifications_error",
            str(error),
        )
        raise

    save_raw_response(
        ticket_id,
        "generate_clarifications_raw",
        raw_response,
    )

    response_content = raw_response

    try:
        _assert_llm_json_candidate(response_content)
        parsed = parse_json(response_content)
        parsed = _normalize_clarifications(parsed)

        questions = _filter_and_limit_questions(
            questions=parsed.get("clarification_questions", []),
            answered_clarifications=answered_clarifications,
            max_questions=max_questions,
        )

        clarification_status = (
            "QUESTIONS_FOUND"
            if questions
            else "NO_OPEN_CLARIFICATIONS"
        )

        clarifications = {
            **parsed,
            "clarification_round": next_round,
            "max_clarification_rounds": max_rounds,
            "max_clarifications_per_round": max_questions,
            "clarification_status": clarification_status,
            "clarification_questions": questions,
            "answered_clarifications_count": len(answered_clarifications),
        }

    except Exception as error:
        clarifications = {
            "clarification_round": next_round,
            "max_clarification_rounds": max_rounds,
            "max_clarifications_per_round": max_questions,
            "clarification_status": "PARSE_ERROR",
            "clarification_questions": [],
            "raw_response": response_content,
            "parse_error": str(error),
        }

        save_raw_response(
            ticket_id,
            "generate_clarifications_parse_error",
            (
                "Failed to parse clarification JSON.\n\n"
                f"Error:\n{error}\n"
            ),
        )

    save_clarifications(ticket_id, clarifications)

    return {
        "clarifications": clarifications,
    }
