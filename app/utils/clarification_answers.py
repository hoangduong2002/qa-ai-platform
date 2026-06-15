from typing import Any


def normalize_clarification_answers(raw) -> list[dict]:
    if raw is None:
        return []

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    if not isinstance(raw, dict):
        return []

    for key in (
        "answers",
        "clarification_answers",
        "answered_clarifications",
    ):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    answers = []

    for question_id, answer in raw.items():
        if isinstance(answer, dict):
            item = dict(answer)
            item.setdefault("id", question_id)
            item.setdefault("question_id", question_id)
            answers.append(item)
        else:
            answers.append(
                {
                    "id": question_id,
                    "answer": answer,
                }
            )

    return answers


def get_clarification_answer_timestamp(item: dict[str, Any]) -> str:
    return str(
        item.get("answered_at")
        or item.get("updated_at")
        or item.get("created_at")
        or ""
    ).strip()


def get_clarification_id(item: dict[str, Any]) -> str:
    return str(
        item.get("question_id")
        or item.get("id")
        or item.get("clarification_id")
        or ""
    ).strip()


def get_clarification_question(item: dict[str, Any]) -> str:
    return str(
        item.get("question")
        or item.get("text")
        or item.get("description")
        or item.get("title")
        or ""
    ).strip()


def get_related_requirement(item: dict[str, Any]):
    return (
        item.get("related_requirement")
        or item.get("related_requirement_id")
        or item.get("related_requirement_ids")
        or item.get("requirement_id")
        or ""
    )


def get_clarification_answer_text(item: dict[str, Any]) -> str:
    return str(
        item.get("final_answer")
        or item.get("answer")
        or item.get("custom_answer")
        or item.get("selected_option_label")
        or ""
    ).strip()


def normalize_question_text(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def merge_clarifications_with_answers(
    clarifications,
    answers,
) -> list[dict]:
    normalized_answers = normalize_clarification_answers(answers)
    answer_by_id = {}
    answer_by_question = {}

    for item in normalized_answers:
        question_id = get_clarification_id(item)
        question_text = normalize_question_text(get_clarification_question(item))

        if question_id:
            answer_by_id[question_id] = item
        if question_text:
            answer_by_question[question_text] = item

    matched_answer_keys = set()
    merged = []

    for index, raw_question in enumerate(clarifications or [], start=1):
        question = dict(raw_question) if isinstance(raw_question, dict) else {}
        question_id = get_clarification_id(question) or f"Q{index:03d}"
        question_text = get_clarification_question(question)
        answer_info = answer_by_id.get(question_id, {})

        if not answer_info:
            answer_info = answer_by_question.get(
                normalize_question_text(question_text),
                {},
            )

        answer = get_clarification_answer_text(answer_info) if answer_info else ""
        answered_at = (
            get_clarification_answer_timestamp(answer_info)
            if answer_info
            else ""
        )

        if answer_info:
            answer_id = get_clarification_id(answer_info)
            answer_question = normalize_question_text(
                get_clarification_question(answer_info)
            )
            if answer_id:
                matched_answer_keys.add(("id", answer_id))
            if answer_question:
                matched_answer_keys.add(("question", answer_question))

        question["id"] = question.get("id") or question_id
        question["question_id"] = question_id
        question["question"] = question_text
        question["answer"] = answer
        question["answer_status"] = "Answered" if answer else "Unanswered"
        question["answered_at"] = answered_at
        question["impact"] = question.get("impact") or question.get("reason", "")
        question["reason"] = question.get("reason", "")
        question["priority"] = question.get("priority") or question.get("severity", "")
        question["category"] = question.get("category") or question.get("type", "")
        question["related_requirement"] = get_related_requirement(question)

        merged.append(question)

    for item in normalized_answers:
        question_id = get_clarification_id(item)
        question_text = get_clarification_question(item)
        normalized_question = normalize_question_text(question_text)

        if (
            question_id
            and ("id", question_id) in matched_answer_keys
        ) or (
            normalized_question
            and ("question", normalized_question) in matched_answer_keys
        ):
            continue

        answer = get_clarification_answer_text(item)
        merged.append(
            {
                "id": question_id,
                "question_id": question_id,
                "question": question_text,
                "answer": answer,
                "answer_status": "Answered" if answer else "Unanswered",
                "answered_at": get_clarification_answer_timestamp(item),
                "impact": item.get("impact") or item.get("reason", ""),
                "reason": item.get("reason", ""),
                "priority": item.get("priority") or item.get("severity", ""),
                "category": item.get("category") or item.get("type", ""),
                "related_requirement": get_related_requirement(item),
            }
        )

    return merged


def count_matched_clarification_answers(
    clarifications,
    answers,
) -> int:
    merged = merge_clarifications_with_answers(clarifications, answers)
    question_ids = {
        get_clarification_id(item)
        for item in clarifications or []
        if isinstance(item, dict)
    }
    question_texts = {
        normalize_question_text(get_clarification_question(item))
        for item in clarifications or []
        if isinstance(item, dict)
    }

    count = 0
    for item in merged:
        if not item.get("answer"):
            continue
        if (
            get_clarification_id(item) in question_ids
            or normalize_question_text(get_clarification_question(item)) in question_texts
        ):
            count += 1

    return count
