from typing import Any


ALLOWED_TEST_DESIGN_TECHNIQUES = {
    "EP",
    "BVA",
    "Decision Table",
    "State Transition",
    "Pairwise",
    "Error Guessing",
    "Use Case",
    "Security",
    "UX",
}


def _as_list(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _normalize_lower(value: Any) -> str:
    return _normalize_text(value).lower()


def _get_scenario_ids(scenarios: list) -> set[str]:
    return {
        scenario.get("scenario_id")
        for scenario in scenarios
        if isinstance(scenario, dict) and scenario.get("scenario_id")
    }


def _get_testcase_scenario_ids(testcases: list) -> set[str]:
    return {
        testcase.get("scenario_id")
        for testcase in testcases
        if isinstance(testcase, dict) and testcase.get("scenario_id")
    }


def _is_generic_expected_result(expected_results: list) -> bool:
    expected_text = " ".join(
        str(item)
        for item in _as_list(expected_results)
    ).lower()

    generic_phrases = [
        "works correctly",
        "system works correctly",
        "system behaves correctly",
        "appropriate message",
        "valid error message",
        "error message is displayed",
        "success message is displayed",
        "operation is successful",
        "validation error is displayed",
    ]

    return any(
        phrase in expected_text
        for phrase in generic_phrases
    )


def _has_concrete_test_data_in_steps(test_steps: list) -> bool:
    steps_text = " ".join(
        str(item)
        for item in _as_list(test_steps)
    ).lower()

    indicators = [
        "'",
        "@",
        "exactly ",
        "less than",
        "greater than",
        "minimum",
        "maximum",
        "invalid",
        "valid",
        "empty",
        "blank",
        "expired",
        "duplicate",
        "123",
        "example.com",
    ]

    return any(
        indicator in steps_text
        for indicator in indicators
    )


def _expected_technique_for_type(testcase_type: str) -> set[str]:
    normalized_type = _normalize_lower(testcase_type)

    if normalized_type in [
        "boundary",
        "boundary value",
        "bva",
    ]:
        return {"BVA"}

    if normalized_type in [
        "business rule",
        "business_rule",
        "decision",
        "decision table",
    ]:
        return {"Decision Table", "EP"}

    if normalized_type in [
        "state",
        "state transition",
        "workflow",
        "lifecycle",
    ]:
        return {"State Transition"}

    if normalized_type in [
        "security",
        "permission",
        "permissions",
        "authorization",
        "authentication",
    ]:
        return {"Security"}

    if normalized_type in [
        "ux",
        "ui",
        "ux_ui",
        "usability",
    ]:
        return {"UX"}

    if normalized_type in [
        "positive",
        "negative",
        "validation",
    ]:
        return {"EP", "BVA", "Use Case", "Error Guessing"}

    if normalized_type in [
        "integration",
        "network",
        "api",
    ]:
        return {"Use Case", "Error Guessing"}

    return ALLOWED_TEST_DESIGN_TECHNIQUES


def _evaluate_traceability(testcase: dict) -> list[dict]:
    issues = []
    testcase_id = testcase.get("testcase_id", "")

    if not testcase.get("related_requirement_ids"):
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Missing related_requirement_ids.",
                "impact": "High",
                "recommendation": "Map this test case to at least one requirement ID.",
            }
        )

    if not testcase.get("traceability"):
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Missing traceability.",
                "impact": "High",
                "recommendation": "Populate traceability from related requirement IDs.",
            }
        )

    return issues


def _evaluate_test_design(testcase: dict) -> list[dict]:
    issues = []

    testcase_id = testcase.get("testcase_id", "")
    testcase_type = testcase.get("type", "")
    technique = testcase.get("technique", "")

    normalized_technique = _normalize_text(technique)

    if not normalized_technique:
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Missing test design technique.",
                "impact": "Medium",
                "recommendation": "Add a technique such as EP, BVA, Decision Table, State Transition, Security, or Use Case.",
            }
        )
        return issues

    if normalized_technique not in ALLOWED_TEST_DESIGN_TECHNIQUES:
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": f"Unsupported test design technique: {normalized_technique}.",
                "impact": "Medium",
                "recommendation": "Use one of: EP, BVA, Decision Table, State Transition, Pairwise, Error Guessing, Use Case, Security, UX.",
            }
        )
        return issues

    expected_techniques = _expected_technique_for_type(testcase_type)

    if normalized_technique not in expected_techniques:
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": (
                    f"Technique '{normalized_technique}' may not match "
                    f"test type '{testcase_type}'."
                ),
                "impact": "Low",
                "recommendation": (
                    "Review whether the test case should use "
                    f"{', '.join(sorted(expected_techniques))}."
                ),
            }
        )

    return issues


def _evaluate_execution_readiness(testcase: dict) -> list[dict]:
    issues = []

    testcase_id = testcase.get("testcase_id", "")
    test_steps = testcase.get("test_steps", [])
    expected_results = testcase.get("expected_results", [])

    if not isinstance(test_steps, list) or len(test_steps) < 3:
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Test steps are missing or too short.",
                "impact": "Medium",
                "recommendation": "Add 3 to 6 executable test steps.",
            }
        )

    if not isinstance(expected_results, list) or len(expected_results) < 2:
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Expected results are missing or too short.",
                "impact": "Medium",
                "recommendation": "Add 2 to 4 verifiable expected results.",
            }
        )

    if isinstance(expected_results, list) and _is_generic_expected_result(
        expected_results
    ):
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Expected result is too generic.",
                "impact": "Low",
                "recommendation": "Use concrete and verifiable expected results.",
            }
        )

    if isinstance(test_steps, list) and not _has_concrete_test_data_in_steps(
        test_steps
    ):
        issues.append(
            {
                "testcase_id": testcase_id,
                "issue": "Test steps may not contain concrete test data.",
                "impact": "Low",
                "recommendation": "Include representative values directly in the steps.",
            }
        )

    return issues


def calculate_deterministic_coverage_score(
    function_scenarios: list,
    function_testcases: list,
) -> dict:
    scenario_ids = _get_scenario_ids(function_scenarios)
    testcase_scenario_ids = _get_testcase_scenario_ids(function_testcases)

    covered_scenario_ids = scenario_ids.intersection(testcase_scenario_ids)
    missing_scenario_ids = sorted(scenario_ids - testcase_scenario_ids)

    total_scenarios = len(scenario_ids)
    covered_scenario_count = len(covered_scenario_ids)

    if total_scenarios:
        scenario_coverage_score = round(
            covered_scenario_count / total_scenarios * 40
        )
    else:
        scenario_coverage_score = 0

    traceability_issues = []
    technique_issues = []
    execution_readiness_issues = []

    for testcase in function_testcases:
        if not isinstance(testcase, dict):
            continue

        traceability_issues.extend(
            _evaluate_traceability(testcase)
        )

        technique_issues.extend(
            _evaluate_test_design(testcase)
        )

        execution_readiness_issues.extend(
            _evaluate_execution_readiness(testcase)
        )

    traceability_penalty = 0
    for issue in traceability_issues:
        impact = _normalize_lower(issue.get("impact"))

        if impact == "high":
            traceability_penalty += 4
        elif impact == "medium":
            traceability_penalty += 2
        else:
            traceability_penalty += 1

    technique_penalty = 0
    for issue in technique_issues:
        impact = _normalize_lower(issue.get("impact"))

        if impact == "high":
            technique_penalty += 4
        elif impact == "medium":
            technique_penalty += 2
        else:
            technique_penalty += 1

    readiness_penalty = 0
    for issue in execution_readiness_issues:
        impact = _normalize_lower(issue.get("impact"))

        if impact == "high":
            readiness_penalty += 4
        elif impact == "medium":
            readiness_penalty += 2
        else:
            readiness_penalty += 1

    traceability_score = max(0, 20 - traceability_penalty)
    test_design_score = max(0, 20 - technique_penalty)
    execution_readiness_score = max(0, 20 - readiness_penalty)

    coverage_score = (
        scenario_coverage_score
        + traceability_score
        + test_design_score
        + execution_readiness_score
    )

    coverage_score = min(100, max(0, coverage_score))

    missing_scenarios = []

    for scenario_id in missing_scenario_ids:
        scenario = next(
            (
                item
                for item in function_scenarios
                if isinstance(item, dict)
                and item.get("scenario_id") == scenario_id
            ),
            {},
        )

        missing_scenarios.append(
            {
                "scenario_id": scenario_id,
                "title": scenario.get("title", ""),
                "reason": "No test case found for this scenario.",
                "related_requirement_ids": scenario.get(
                    "related_requirement_ids",
                    [],
                ),
            }
        )

    weak_testcases = (
        technique_issues
        + execution_readiness_issues
    )

    approved_by_rule = (
        coverage_score >= 90
        and not missing_scenarios
        and not traceability_issues
        and not execution_readiness_issues
    )

    return {
        "coverage_score": coverage_score,
        "approved_by_rule": approved_by_rule,
        "scenario_coverage_score": scenario_coverage_score,
        "traceability_score": traceability_score,
        "test_design_score": test_design_score,
        "execution_readiness_score": execution_readiness_score,
        "covered_scenario_count": covered_scenario_count,
        "total_scenario_count": total_scenarios,
        "missing_scenario_ids": missing_scenario_ids,
        "missing_scenarios": missing_scenarios,
        "traceability_issues": traceability_issues,
        "technique_issues": technique_issues,
        "execution_readiness_issues": execution_readiness_issues,
        "weak_testcases": weak_testcases,
    }


def build_deterministic_coverage_review(
    function_id: str,
    function_name: str,
    function_scenarios: list,
    function_testcases: list,
) -> dict:
    score_result = calculate_deterministic_coverage_score(
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
    )

    scenario_ids = _get_scenario_ids(function_scenarios)
    covered_scenario_ids = _get_testcase_scenario_ids(
        function_testcases
    ).intersection(scenario_ids)

    testcase_by_scenario = {}

    for testcase in function_testcases:
        if not isinstance(testcase, dict):
            continue

        scenario_id = testcase.get("scenario_id")

        if not scenario_id:
            continue

        testcase_by_scenario.setdefault(scenario_id, []).append(
            testcase.get("testcase_id", "")
        )

    return {
        "function_id": function_id,
        "function_name": function_name,
        "coverage_score": score_result["coverage_score"],
        "approved_by_ai": score_result["approved_by_rule"],
        "review_mode": "DETERMINISTIC_SCORE",
        "summary": (
            "Coverage review was generated by deterministic scoring. "
            f"Scenario coverage={score_result['scenario_coverage_score']}/40, "
            f"Traceability={score_result['traceability_score']}/20, "
            f"Test design={score_result['test_design_score']}/20, "
            f"Execution readiness={score_result['execution_readiness_score']}/20."
        ),
        "scenario_count": len(scenario_ids),
        "testcase_count": len(function_testcases),
        "covered_scenarios": [
            {
                "scenario_id": scenario_id,
                "testcase_ids": testcase_by_scenario.get(scenario_id, []),
                "status": "Covered",
            }
            for scenario_id in sorted(covered_scenario_ids)
        ],
        "missing_scenarios": score_result["missing_scenarios"],
        "weak_testcases": score_result["weak_testcases"],
        "missing_testcases": [],
        "traceability_issues": score_result["traceability_issues"],
        "recommendations": _build_recommendations(score_result),
        "score_breakdown": {
            "scenario_coverage_score": score_result["scenario_coverage_score"],
            "traceability_score": score_result["traceability_score"],
            "test_design_score": score_result["test_design_score"],
            "execution_readiness_score": score_result[
                "execution_readiness_score"
            ],
        },
    }


def build_deterministic_final_review(
    function_id: str,
    function_name: str,
    function_scenarios: list,
    function_testcases: list,
    previous_coverage_review: dict | None = None,
) -> dict:
    score_result = calculate_deterministic_coverage_score(
        function_scenarios=function_scenarios,
        function_testcases=function_testcases,
    )

    previous_coverage_review = previous_coverage_review or {}

    remaining_gaps = []
    remaining_gaps.extend(score_result["missing_scenarios"])
    remaining_gaps.extend(score_result["weak_testcases"])

    ready_for_execution = (
        score_result["coverage_score"] >= 90
        and not score_result["missing_scenarios"]
        and not score_result["traceability_issues"]
        and not score_result["execution_readiness_issues"]
    )

    return {
        "function_id": function_id,
        "function_name": function_name,
        "final_coverage_score": score_result["coverage_score"],
        "coverage_score": score_result["coverage_score"],
        "approved_by_ai": ready_for_execution,
        "ready_for_execution": ready_for_execution,
        "review_mode": "DETERMINISTIC_SCORE",
        "summary": (
            "Final review was generated by deterministic scoring. "
            f"Scenario coverage={score_result['scenario_coverage_score']}/40, "
            f"Traceability={score_result['traceability_score']}/20, "
            f"Test design={score_result['test_design_score']}/20, "
            f"Execution readiness={score_result['execution_readiness_score']}/20."
        ),
        "scenario_count": score_result["total_scenario_count"],
        "testcase_count": len(function_testcases),
        "resolved_issues": previous_coverage_review.get(
            "recommendations",
            [],
        ),
        "remaining_gaps": remaining_gaps,
        "traceability_issues": score_result["traceability_issues"],
        "execution_readiness_issues": score_result[
            "execution_readiness_issues"
        ],
        "final_recommendations": _build_recommendations(score_result),
        "score_breakdown": {
            "scenario_coverage_score": score_result["scenario_coverage_score"],
            "traceability_score": score_result["traceability_score"],
            "test_design_score": score_result["test_design_score"],
            "execution_readiness_score": score_result[
                "execution_readiness_score"
            ],
        },
    }


def _build_recommendations(score_result: dict) -> list[dict]:
    recommendations = []

    if score_result.get("missing_scenarios"):
        recommendations.append(
            {
                "priority": "High",
                "recommendation": "Add test cases for missing scenarios.",
                "related_items": [
                    item.get("scenario_id")
                    for item in score_result.get("missing_scenarios", [])
                    if isinstance(item, dict)
                ],
            }
        )

    if score_result.get("traceability_issues"):
        recommendations.append(
            {
                "priority": "High",
                "recommendation": "Fix traceability issues before approval.",
                "related_items": [
                    item.get("testcase_id")
                    for item in score_result.get("traceability_issues", [])
                    if isinstance(item, dict)
                ],
            }
        )

    if score_result.get("technique_issues"):
        recommendations.append(
            {
                "priority": "Medium",
                "recommendation": "Review test design techniques for weak test cases.",
                "related_items": [
                    item.get("testcase_id")
                    for item in score_result.get("technique_issues", [])
                    if isinstance(item, dict)
                ],
            }
        )

    if score_result.get("execution_readiness_issues"):
        recommendations.append(
            {
                "priority": "Medium",
                "recommendation": "Improve execution readiness by making steps and expected results more concrete.",
                "related_items": [
                    item.get("testcase_id")
                    for item in score_result.get(
                        "execution_readiness_issues",
                        []
                    )
                    if isinstance(item, dict)
                ],
            }
        )

    return recommendations