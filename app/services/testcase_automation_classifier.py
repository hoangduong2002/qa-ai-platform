from __future__ import annotations

from collections import Counter
from typing import Any


VALID_EXECUTION_TYPES = {"AUTOMATION", "MANUAL", "HYBRID"}
VALID_AUTOMATION_PRIORITIES = {"High", "Medium", "Low", "Not Applicable"}
AUTOMATION_TOOL = "Playwright"

MANUAL_BLOCKER_KEYWORDS = [
    "visual",
    "layout",
    "color",
    "look and feel",
    "usability",
    "human judgment",
    "email inbox",
    "sms",
    "phone call",
    "third-party",
    "approval",
    "print",
    "scan",
    "signature",
    "external system",
    "manual verification",
]

AUTOMATION_CANDIDATE_KEYWORDS = [
    "click",
    "input",
    "select",
    "submit",
    "navigate",
    "search",
    "filter",
    "sort",
    "validate message",
    "display error",
    "create",
    "update",
    "delete",
    "login",
]


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(val)}" for key, val in value.items())
    return str(value)


def _testcase_text(testcase: dict) -> str:
    fields = [
        "title",
        "type",
        "technique",
        "priority",
        "preconditions",
        "steps",
        "test_steps",
        "expected",
        "expected_result",
        "expected_results",
        "automation_reason",
        "automation_blockers",
        "manual_reason",
    ]
    return " ".join(_text(testcase.get(field)) for field in fields).lower()


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _normalize_execution_type(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in VALID_EXECUTION_TYPES else ""


def _normalize_priority(value: Any) -> str:
    normalized = str(value or "").strip()
    for candidate in VALID_AUTOMATION_PRIORITIES:
        if normalized.lower() == candidate.lower():
            return candidate
    return ""


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "automation"}
    return bool(value)


def _unique(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            result.append(clean)
    return result


def _automation_priority(testcase: dict, execution_type: str) -> str:
    if execution_type == "MANUAL":
        return "Not Applicable"

    existing = _normalize_priority(testcase.get("automation_priority"))
    if existing and existing != "Not Applicable":
        return existing

    priority = str(testcase.get("priority") or "").strip().lower()
    if priority == "high":
        return "High"
    if priority == "medium":
        return "Medium"
    if priority == "low":
        return "Low"
    return "Medium" if execution_type == "AUTOMATION" else "Low"


def classify_testcase_automation(testcase: dict) -> dict:
    if not isinstance(testcase, dict):
        return testcase

    item = dict(testcase)
    searchable_text = _testcase_text(item)
    manual_matches = _matched_keywords(searchable_text, MANUAL_BLOCKER_KEYWORDS)
    automation_matches = _matched_keywords(
        searchable_text,
        AUTOMATION_CANDIDATE_KEYWORDS,
    )
    existing_execution_type = _normalize_execution_type(
        item.get("execution_type")
    )
    existing_candidate = (
        _bool(item.get("automation_candidate"))
        if "automation_candidate" in item
        else None
    )

    if manual_matches and automation_matches:
        execution_type = "HYBRID"
    elif manual_matches:
        execution_type = "MANUAL"
    elif automation_matches:
        execution_type = "AUTOMATION"
    elif existing_execution_type:
        execution_type = existing_execution_type
    elif existing_candidate is True:
        execution_type = "AUTOMATION"
    else:
        execution_type = "MANUAL"

    automation_candidate = execution_type in {"AUTOMATION", "HYBRID"}
    blockers = _unique(
        _as_list(item.get("automation_blockers")) + manual_matches
    )

    item["execution_type"] = execution_type
    item["automation_candidate"] = automation_candidate
    item["automation_tool"] = (
        AUTOMATION_TOOL if automation_candidate else str(item.get("automation_tool") or "")
    )
    item["automation_priority"] = _automation_priority(item, execution_type)
    item["automation_blockers"] = blockers

    if automation_candidate:
        item["automation_reason"] = (
            str(item.get("automation_reason") or "").strip()
            or "Suitable for Playwright because the flow uses browser UI actions and deterministic assertions."
        )
    else:
        item["automation_reason"] = ""

    if execution_type in {"MANUAL", "HYBRID"}:
        item["manual_reason"] = (
            str(item.get("manual_reason") or "").strip()
            or (
                "Requires manual execution or review because it includes: "
                + ", ".join(blockers)
                + "."
                if blockers
                else "Requires manual execution based on the provided classification."
            )
        )
    else:
        item["manual_reason"] = ""

    return item


def classify_testcases_automation(testcases: list[dict]) -> list[dict]:
    return [
        classify_testcase_automation(testcase)
        for testcase in testcases or []
        if isinstance(testcase, dict)
    ]


def summarize_automation_classification(testcases: list[dict]) -> dict:
    classified = classify_testcases_automation(testcases)
    total = len(classified)
    automation_count = sum(
        1 for testcase in classified if testcase.get("automation_candidate")
    )
    manual_count = sum(
        1 for testcase in classified if testcase.get("execution_type") == "MANUAL"
    )
    hybrid_count = sum(
        1 for testcase in classified if testcase.get("execution_type") == "HYBRID"
    )
    high_priority_count = sum(
        1
        for testcase in classified
        if testcase.get("automation_candidate")
        and testcase.get("automation_priority") == "High"
    )

    blocker_counter = Counter()
    for testcase in classified:
        blocker_counter.update(_as_list(testcase.get("automation_blockers")))

    return {
        "total_testcases": total,
        "automation_candidates": automation_count,
        "manual_testcases": manual_count,
        "hybrid_testcases": hybrid_count,
        "automation_coverage_percent": round(
            (automation_count / total) * 100,
            2,
        ) if total else 0,
        "high_priority_automation_count": high_priority_count,
        "top_automation_blockers": [
            f"{blocker} ({count})"
            for blocker, count in blocker_counter.most_common(10)
        ],
    }
