from __future__ import annotations

import re

from app.services.test_case_generator_v2.models import TestCaseSetV2


def _text(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _title(item: dict) -> str:
    return _text(item.get("title") or item.get("testcase_name"))


def _duplicate_rate(items: list[dict]) -> float:
    fingerprints = []
    for item in items:
        title = _title(item)
        steps = item.get("steps") or item.get("test_steps") or []
        fingerprints.append((title, _text(steps)))
    return round((len(fingerprints) - len(set(fingerprints))) / len(fingerprints), 4) if fingerprints else 0.0


def _refs(item: dict, *keys: str) -> set[str]:
    result = set()
    for key in keys:
        value = item.get(key, [])
        if isinstance(value, str):
            value = [part.strip() for part in re.split(r"[,;]", value)]
        if isinstance(value, list):
            result.update(str(part).strip() for part in value if str(part).strip())
    return result


def _coverage_rate(items: list[dict], expected: set[str], *keys: str) -> float:
    if not expected:
        return 1.0
    actual = set().union(*(_refs(item, *keys) for item in items)) if items else set()
    return round(len(actual & expected) / len(expected), 4)


def compare_generators(
    *,
    ticket_id: str,
    v1_testcases: list[dict],
    v2: TestCaseSetV2,
    inputs: dict,
) -> dict:
    v2_items = [item.model_dump(mode="json") for item in v2.test_cases]
    coverage_conditions = (inputs.get("coverage_model") or {}).get("coverage_conditions", [])
    coverage_ids = {
        str(item.get("condition_id"))
        for item in coverage_conditions
        if isinstance(item, dict) and item.get("condition_id")
    }
    critical_ids = {
        str(item.get("condition_id"))
        for item in coverage_conditions
        if isinstance(item, dict)
        and item.get("condition_id")
        and (
            str(item.get("risk_priority") or "").upper() in {"HIGH", "CRITICAL"}
            or item.get("mandatory") is True
        )
    }
    requirement_ids = set((inputs.get("coverage_model") or {}).get("requirement_refs", []))

    v1_titles = {_title(item) for item in v1_testcases if _title(item)}
    v2_titles = {_title(item) for item in v2_items if _title(item)}
    v2_expected = [result for item in v2.test_cases for result in item.expected_results]
    supported_results = sum(
        1 for result in v2_expected
        if any(ref.supports_expected_behavior() for ref in result.source_refs)
        or result.assumption
        or result.unresolved_question
    )

    return {
        "schema_version": "1.0",
        "ticket_id": ticket_id,
        "production_generator": "v1",
        "shadow_generator": "v2",
        "metrics": {
            "test_count": {"v1": len(v1_testcases), "v2": len(v2_items)},
            "acceptance_criteria_coverage": {
                "v1": _coverage_rate(v1_testcases, requirement_ids, "related_requirement_ids", "related_requirements", "requirement_refs"),
                "v2": _coverage_rate(v2_items, requirement_ids, "requirement_refs"),
            },
            "critical_condition_coverage": {
                "v1": _coverage_rate(v1_testcases, critical_ids, "coverage_refs", "coverage_ids"),
                "v2": _coverage_rate(v2_items, critical_ids, "coverage_refs"),
            },
            "selected_condition_coverage": {
                "v1": _coverage_rate(v1_testcases, coverage_ids, "coverage_refs", "coverage_ids"),
                "v2": _coverage_rate(v2_items, coverage_ids, "coverage_refs"),
            },
            "duplicate_rate": {"v1": _duplicate_rate(v1_testcases), "v2": _duplicate_rate(v2_items)},
            "unsupported_expected_result_count": {
                "v1": sum(len(item.get("expected_results") or []) for item in v1_testcases),
                "v2": len(v2_expected) - supported_results,
            },
            "missing_test_data_count": {
                "v1": sum(1 for item in v1_testcases if not item.get("test_data")),
                "v2": sum(1 for item in v2_items if not item.get("test_data")),
            },
            "source_reference_completeness": {
                "v1": 0.0 if v1_testcases else 1.0,
                "v2": round(supported_results / len(v2_expected), 4) if v2_expected else 1.0,
            },
        },
        "cases_unique_to_v1": sorted(v1_titles - v2_titles),
        "cases_unique_to_v2": sorted(v2_titles - v1_titles),
    }
