from __future__ import annotations

from evaluation.metrics.deterministic import calculate_ticket_metrics


def test_calculate_ticket_metrics_core_counts() -> None:
    metrics = calculate_ticket_metrics(
        expected_business_rules=["required fields block submission"],
        expected_results=["error messages are shown"],
        critical_scenarios=["missing shipping address"],
        critical_test_cases=["checkout submission is blocked"],
        expected_missing_information=["payment method in scope"],
        expected_contradictions=["must allow checkout without address"],
        expected_ambiguities=["required fields vary by region"],
        acceptance_criteria_required_items=["error messages are shown"],
        forbidden_assumptions=["guest checkout always enabled"],
        analysis={
            "requirement_items": [
                {"description": "Required fields block submission"}
            ]
        },
        scenarios=[
            {"title": "Missing shipping address during checkout"}
        ],
        testcases=[
            {
                "test_case": "Checkout submission is blocked",
                "precondition": "User is at checkout",
                "steps": "Leave shipping address blank",
                "expected_result": "Error messages are shown",
            }
        ],
        structured_analysis={
            "schema_version": "1.0",
            "business_rules": [
                {
                    "text": "required fields block submission",
                    "confidence": 1.0,
                    "classification": "EXPLICIT",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_DESCRIPTION",
                            "source_identifier": "desc-1",
                            "source_excerpt": "required fields block submission",
                            "confidence": 1.0,
                            "classification": "EXPLICIT",
                        }
                    ],
                }
            ],
            "expected_results": [
                {
                    "text": "error messages are shown",
                    "confidence": 1.0,
                    "classification": "EXPLICIT",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_ACCEPTANCE_CRITERIA",
                            "source_location": "ac-1",
                            "confidence": 1.0,
                            "classification": "EXPLICIT",
                        }
                    ],
                }
            ],
            "missing_information": [
                {
                    "text": "payment method in scope",
                    "confidence": 1.0,
                    "classification": "MISSING_INFORMATION",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "UNKNOWN",
                            "source_identifier": "gap-1",
                            "confidence": 1.0,
                            "classification": "MISSING_INFORMATION",
                        }
                    ],
                }
            ],
            "ambiguities": [
                {
                    "text": "required fields vary by region",
                    "confidence": 1.0,
                    "classification": "AMBIGUOUS",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_COMMENT",
                            "source_identifier": "comment-1",
                            "confidence": 1.0,
                            "classification": "AMBIGUOUS",
                        }
                    ],
                },
                {
                    "text": "possibly maybe maybe",
                    "confidence": 0.5,
                    "classification": "AMBIGUOUS",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "UNKNOWN",
                            "source_identifier": "comment-2",
                            "confidence": 0.5,
                            "classification": "AMBIGUOUS",
                        }
                    ],
                },
            ],
            "contradictions": [],
            "assumptions": [
                {
                    "text": "guest checkout always enabled",
                    "confidence": 0.2,
                    "classification": "ASSUMPTION",
                    "provenance": [],
                }
            ],
        },
        workflow_failed=False,
    )

    assert metrics["expected_business_rule_match_count"] == 1
    assert metrics["critical_scenario_coverage"] == 1
    assert metrics["critical_test_case_coverage"] == 1
    assert metrics["acceptance_criteria_coverage"] == 1.0
    assert metrics["workflow_failure_rate"] == 0.0
    assert metrics["business_rule_extraction_recall"] == 1.0
    assert metrics["expected_result_extraction_recall"] == 1.0
    assert metrics["missing_information_recall"] == 1.0
    assert metrics["false_ambiguity_rate"] == 0.5
    assert metrics["unsupported_assumption_count"] == 1
    assert metrics["contradiction_detection"] == 0.0
    assert metrics["schema_valid_response_rate"] == 1.0
