from __future__ import annotations

import re
from typing import Any

from evaluation.metrics.semantic_matcher import (
    ConservativeSemanticMatcher,
    SemanticMatcher,
)


UNSUPPORTED_VALUE_PATTERNS = (
    "tbd",
    "n/a",
    "na",
    "unknown",
    "not provided",
    "to be decided",
    "to be confirmed",
)


def _to_text_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if isinstance(value, list):
        result: list[str] = []

        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                for key in ("title", "description", "objective", "name"):
                    raw = item.get(key)
                    if isinstance(raw, str) and raw.strip():
                        result.append(raw.strip())
                        break

        return result

    return []


def extract_business_rule_texts(analysis: dict[str, Any]) -> list[str]:
    texts: list[str] = []

    for item in analysis.get("requirement_items", []) or []:
        if not isinstance(item, dict):
            continue

        for key in ("description", "title", "rule"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                texts.append(raw.strip())
                break

    return texts


def extract_scenario_texts(scenarios: list[dict[str, Any]] | list[Any]) -> list[str]:
    texts: list[str] = []

    for scenario in scenarios or []:
        if not isinstance(scenario, dict):
            continue

        for key in ("scenario_title", "title", "name", "objective"):
            raw = scenario.get(key)
            if isinstance(raw, str) and raw.strip():
                texts.append(raw.strip())
                break

    return texts


def extract_testcase_texts(testcases: list[dict[str, Any]] | list[Any]) -> list[str]:
    texts: list[str] = []

    for testcase in testcases or []:
        if not isinstance(testcase, dict):
            continue

        for key in ("test_case", "title", "test_name", "objective"):
            raw = testcase.get(key)
            if isinstance(raw, str) and raw.strip():
                texts.append(raw.strip())
                break

        for key in ("precondition", "steps", "expected_result"):
            raw = testcase.get(key)
            if isinstance(raw, str) and raw.strip():
                texts.append(raw.strip())

    return texts


def _structured_fact_texts(structured_analysis: dict[str, Any], field_name: str) -> list[str]:
    items = structured_analysis.get(field_name, []) if isinstance(structured_analysis, dict) else []
    texts: list[str] = []

    if not isinstance(items, list):
        return texts

    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if text:
            texts.append(text)

    return texts


def _structured_fact_items(structured_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(structured_analysis, dict):
        return []

    fields = [
        "business_goal",
        "actors",
        "preconditions",
        "triggers",
        "business_rules",
        "input_data",
        "expected_results",
        "error_behaviors",
        "state_transitions",
        "permissions",
        "integrations",
        "non_functional_requirements",
        "out_of_scope",
        "ambiguities",
        "contradictions",
        "assumptions",
        "missing_information",
    ]

    facts: list[dict[str, Any]] = []

    for field in fields:
        value = structured_analysis.get(field, [])
        if not isinstance(value, list):
            continue

        for item in value:
            if isinstance(item, dict):
                facts.append(item)

    return facts


def _schema_valid_response_rate(structured_analysis: dict[str, Any]) -> float:
    if not isinstance(structured_analysis, dict):
        return 0.0

    return 1.0 if structured_analysis.get("schema_version") == "1.0" else 0.0


def _source_reference_completeness(structured_analysis: dict[str, Any]) -> float:
    facts = _structured_fact_items(structured_analysis)

    if not facts:
        return 0.0

    complete = 0

    for fact in facts:
        refs = fact.get("provenance", [])

        if not isinstance(refs, list) or not refs:
            continue

        has_usable_ref = False

        for ref in refs:
            if not isinstance(ref, dict):
                continue

            has_source_classification = bool(str(ref.get("source_classification", "")).strip())
            has_confidence = isinstance(ref.get("confidence"), (int, float))
            has_classification = bool(str(ref.get("classification", "")).strip())
            has_locator = any(
                str(ref.get(key, "")).strip()
                for key in ("source_identifier", "source_location", "source_excerpt")
            )

            if has_source_classification and has_confidence and has_classification and has_locator:
                has_usable_ref = True
                break

        if has_usable_ref:
            complete += 1

    return complete / len(facts)


def _unsupported_assumption_count(structured_analysis: dict[str, Any]) -> int:
    assumptions = structured_analysis.get("assumptions", []) if isinstance(structured_analysis, dict) else []

    if not isinstance(assumptions, list):
        return 0

    count = 0

    for fact in assumptions:
        if not isinstance(fact, dict):
            continue

        refs = fact.get("provenance", [])
        if not isinstance(refs, list) or not refs:
            count += 1

    return count


def _normalize_for_duplicate(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def duplicate_testcase_rate(testcases: list[dict[str, Any]] | list[Any]) -> tuple[int, float]:
    if not testcases:
        return 0, 0.0

    seen: set[str] = set()
    duplicates = 0

    for testcase in testcases:
        if not isinstance(testcase, dict):
            continue

        parts = [
            testcase.get("test_case", ""),
            testcase.get("precondition", ""),
            testcase.get("steps", ""),
            testcase.get("expected_result", ""),
        ]
        fingerprint = " | ".join(_normalize_for_duplicate(str(part)) for part in parts)

        if fingerprint in seen:
            duplicates += 1
        else:
            seen.add(fingerprint)

    rate = duplicates / len(testcases)
    return duplicates, rate


def forbidden_assumption_count(
    forbidden_assumptions: list[str],
    text_corpus: list[str],
    matcher: SemanticMatcher,
) -> int:
    return matcher.count_matches(forbidden_assumptions, text_corpus)


def unsupported_value_count(testcases: list[dict[str, Any]] | list[Any]) -> int:
    count = 0

    for testcase in testcases or []:
        if not isinstance(testcase, dict):
            continue

        for key in ("precondition", "steps", "expected_result"):
            raw = str(testcase.get(key, "")).lower()
            if any(pattern in raw for pattern in UNSUPPORTED_VALUE_PATTERNS):
                count += 1

    return count


def empty_required_field_count(testcases: list[dict[str, Any]] | list[Any]) -> int:
    required_fields = ("test_case", "precondition", "steps", "expected_result")
    count = 0

    for testcase in testcases or []:
        if not isinstance(testcase, dict):
            count += len(required_fields)
            continue

        for field in required_fields:
            raw = testcase.get(field)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                count += 1

    return count


def calculate_ticket_metrics(
    *,
    expected_business_rules: list[str],
    expected_results: list[str],
    critical_scenarios: list[str],
    critical_test_cases: list[str],
    expected_missing_information: list[str],
    expected_contradictions: list[str],
    expected_ambiguities: list[str],
    acceptance_criteria_required_items: list[str],
    forbidden_assumptions: list[str],
    analysis: dict[str, Any],
    structured_analysis: dict[str, Any] | None = None,
    scenarios: list[dict[str, Any]] | list[Any],
    testcases: list[dict[str, Any]] | list[Any],
    workflow_failed: bool,
    matcher: SemanticMatcher | None = None,
    expected_reference_ids: list[str] | None = None,
    retrieved_reference_ids: list[str] | None = None,
    expected_exact_codes: list[str] | None = None,
    retrieved_exact_codes: list[str] | None = None,
) -> dict[str, Any]:
    matcher = matcher or ConservativeSemanticMatcher()
    structured_analysis = structured_analysis or {}

    business_rule_candidates = extract_business_rule_texts(analysis)
    scenario_texts = extract_scenario_texts(scenarios)
    testcase_texts = extract_testcase_texts(testcases)

    business_rule_matches = matcher.count_matches(
        expected_business_rules,
        business_rule_candidates,
    )

    critical_scenario_matches = matcher.count_matches(
        critical_scenarios,
        scenario_texts,
    )

    critical_testcase_matches = matcher.count_matches(
        critical_test_cases,
        testcase_texts,
    )

    acceptance_matches = matcher.count_matches(
        acceptance_criteria_required_items,
        scenario_texts + testcase_texts,
    )

    acceptance_ratio = (
        acceptance_matches / len(acceptance_criteria_required_items)
        if acceptance_criteria_required_items
        else 1.0
    )

    duplicates, duplicate_rate = duplicate_testcase_rate(testcases)

    corpus = business_rule_candidates + scenario_texts + testcase_texts

    structured_business_rules = _structured_fact_texts(structured_analysis, "business_rules")
    structured_expected_results = _structured_fact_texts(structured_analysis, "expected_results")
    structured_missing_information = _structured_fact_texts(structured_analysis, "missing_information")
    structured_ambiguities = _structured_fact_texts(structured_analysis, "ambiguities")
    structured_contradictions = _structured_fact_texts(structured_analysis, "contradictions")

    business_rule_recall = (
        matcher.count_matches(expected_business_rules, structured_business_rules) / len(expected_business_rules)
        if expected_business_rules
        else 1.0
    )

    expected_result_recall = (
        matcher.count_matches(expected_results, structured_expected_results) / len(expected_results)
        if expected_results
        else 1.0
    )

    missing_information_recall = (
        matcher.count_matches(expected_missing_information, structured_missing_information) / len(expected_missing_information)
        if expected_missing_information
        else 1.0
    )

    contradiction_detection = (
        matcher.count_matches(expected_contradictions, structured_contradictions) / len(expected_contradictions)
        if expected_contradictions
        else 1.0
    )

    ambiguity_matches = matcher.count_matches(expected_ambiguities, structured_ambiguities)
    ambiguity_total = len(structured_ambiguities)
    false_ambiguity_rate = (
        max(0, ambiguity_total - ambiguity_matches) / ambiguity_total
        if ambiguity_total > 0
        else 0.0
    )
    ambiguity_precision = (
        ambiguity_matches / ambiguity_total
        if ambiguity_total > 0
        else (1.0 if not expected_ambiguities else 0.0)
    )
    expected_reference_ids = expected_reference_ids or []
    retrieved_reference_ids = retrieved_reference_ids or []
    expected_exact_codes = expected_exact_codes or []
    retrieved_exact_codes = retrieved_exact_codes or []
    top_five = retrieved_reference_ids[:5]
    top_ten = retrieved_reference_ids[:10]
    precision_at_5 = (
        len(set(top_five) & set(expected_reference_ids)) / len(top_five)
        if top_five
        else (1.0 if not expected_reference_ids else 0.0)
    )
    recall_at_10 = (
        len(set(top_ten) & set(expected_reference_ids)) / len(set(expected_reference_ids))
        if expected_reference_ids
        else 1.0
    )
    exact_code_accuracy = (
        len(set(retrieved_exact_codes) & set(expected_exact_codes)) / len(set(expected_exact_codes))
        if expected_exact_codes
        else 1.0
    )
    unsupported_assumptions = _unsupported_assumption_count(structured_analysis)
    structured_assumptions = structured_analysis.get("assumptions", []) if isinstance(structured_analysis, dict) else []
    unsupported_results = unsupported_value_count(testcases)

    return {
        "expected_business_rule_match_count": business_rule_matches,
        "critical_scenario_coverage": critical_scenario_matches,
        "critical_test_case_coverage": critical_testcase_matches,
        "acceptance_criteria_coverage": acceptance_ratio,
        "duplicate_test_case_count": duplicates,
        "duplicate_test_case_rate": duplicate_rate,
        "unsupported_value_count": unsupported_results,
        "unsupported_result_rate": unsupported_results / len(testcases) if testcases else 0.0,
        "unsupported_assumption_count": unsupported_assumptions,
        "unsupported_assumption_rate": unsupported_assumptions / len(structured_assumptions) if structured_assumptions else 0.0,
        "forbidden_assumption_count": forbidden_assumption_count(
            forbidden_assumptions,
            corpus,
            matcher,
        ),
        "empty_required_field_count": empty_required_field_count(testcases),
        "workflow_failure_rate": 1.0 if workflow_failed else 0.0,
        "business_rule_extraction_recall": business_rule_recall,
        "expected_result_extraction_recall": expected_result_recall,
        "missing_information_recall": missing_information_recall,
        "false_ambiguity_rate": false_ambiguity_rate,
        "ambiguity_precision": ambiguity_precision,
        "contradiction_detection": contradiction_detection,
        "contradiction_detection_rate": contradiction_detection,
        "schema_valid_response_rate": _schema_valid_response_rate(structured_analysis),
        "source_reference_completeness": _source_reference_completeness(structured_analysis),
        "critical_condition_coverage": (
            critical_testcase_matches / len(critical_test_cases) if critical_test_cases else 1.0
        ),
        "precision_at_5": precision_at_5,
        "recall_at_10": recall_at_10,
        "exact_code_accuracy": exact_code_accuracy,
        "jira_authority_violation_count": 0,
    }


def calculate_aggregate_metrics(ticket_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not ticket_metrics:
        return {
            "ticket_count": 0,
            "workflow_failure_rate": 0.0,
        }

    aggregate: dict[str, Any] = {"ticket_count": len(ticket_metrics)}
    metric_keys = [
        "expected_business_rule_match_count",
        "critical_scenario_coverage",
        "critical_test_case_coverage",
        "acceptance_criteria_coverage",
        "duplicate_test_case_rate",
        "unsupported_value_count",
        "unsupported_assumption_count",
        "forbidden_assumption_count",
        "empty_required_field_count",
        "workflow_failure_rate",
        "business_rule_extraction_recall",
        "expected_result_extraction_recall",
        "missing_information_recall",
        "false_ambiguity_rate",
        "contradiction_detection",
        "schema_valid_response_rate",
        "source_reference_completeness",
        "unsupported_result_rate",
        "unsupported_assumption_rate",
        "ambiguity_precision",
        "contradiction_detection_rate",
        "critical_condition_coverage",
        "precision_at_5",
        "recall_at_10",
        "exact_code_accuracy",
        "jira_authority_violation_count",
    ]

    for key in metric_keys:
        aggregate[key] = sum(metric.get(key, 0) for metric in ticket_metrics) / len(ticket_metrics)

    return aggregate
