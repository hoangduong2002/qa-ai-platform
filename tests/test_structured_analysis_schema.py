from __future__ import annotations

import pytest

from app.models.structured_analysis_schema import (
    StructuredRequirementAnalysisV1,
    validate_structured_requirement_analysis,
)


def _minimal_payload() -> dict:
    return {
        "schema_version": "1.0",
        "business_goal": [
            {
                "fact_id": "BG-001",
                "text": "Prevent invalid checkout submission",
                "confidence": 0.95,
                "classification": "EXPLICIT",
                "provenance": [
                    {
                        "source_type": "jira",
                        "source_classification": "JIRA_DESCRIPTION",
                        "source_identifier": "DESC-1",
                        "source_excerpt": "must not submit checkout when required fields are blank",
                        "confidence": 0.95,
                        "classification": "EXPLICIT",
                    }
                ],
            }
        ],
        "actors": [],
        "preconditions": [],
        "triggers": [],
        "business_rules": [],
        "input_data": [],
        "expected_results": [],
        "error_behaviors": [],
        "state_transitions": [],
        "permissions": [],
        "integrations": [],
        "non_functional_requirements": [],
        "out_of_scope": [],
        "ambiguities": [],
        "contradictions": [],
        "assumptions": [],
        "missing_information": [],
        "source_references": [],
    }


def test_schema_validation_accepts_valid_payload() -> None:
    parsed = validate_structured_requirement_analysis(_minimal_payload())
    assert isinstance(parsed, StructuredRequirementAnalysisV1)
    assert parsed.schema_version == "1.0"


def test_schema_validation_rejects_missing_fact_text() -> None:
    payload = _minimal_payload()
    payload["business_goal"][0]["text"] = ""

    with pytest.raises(Exception):
        validate_structured_requirement_analysis(payload)


def test_schema_supports_ambiguity_and_contradiction_sections() -> None:
    payload = _minimal_payload()
    payload["ambiguities"] = [
        {
            "text": "The required field list is not explicitly defined by region.",
            "confidence": 0.7,
            "classification": "AMBIGUOUS",
            "provenance": [
                {
                    "source_type": "jira",
                    "source_classification": "JIRA_COMMENT",
                    "source_identifier": "COMMENT-12",
                    "source_excerpt": "Required fields may vary.",
                    "confidence": 0.7,
                    "classification": "AMBIGUOUS",
                }
            ],
        }
    ]
    payload["contradictions"] = [
        {
            "text": "Description says shipping address is required but comment says optional.",
            "confidence": 0.9,
            "classification": "CONTRADICTION",
            "provenance": [
                {
                    "source_type": "jira",
                    "source_classification": "JIRA_DESCRIPTION",
                    "source_identifier": "DESC-1",
                    "confidence": 0.9,
                    "classification": "CONTRADICTION",
                },
                {
                    "source_type": "jira",
                    "source_classification": "JIRA_COMMENT",
                    "source_identifier": "COMMENT-99",
                    "confidence": 0.9,
                    "classification": "CONTRADICTION",
                },
            ],
        }
    ]

    parsed = validate_structured_requirement_analysis(payload)
    assert len(parsed.ambiguities) == 1
    assert len(parsed.contradictions) == 1


def test_schema_supports_assumptions_and_missing_information() -> None:
    payload = _minimal_payload()
    payload["assumptions"] = [
        {
            "text": "Guest checkout is enabled.",
            "confidence": 0.3,
            "classification": "ASSUMPTION",
            "provenance": [],
        }
    ]
    payload["missing_information"] = [
        {
            "text": "No explicit payment-method scope is provided.",
            "confidence": 0.8,
            "classification": "MISSING_INFORMATION",
            "provenance": [
                {
                    "source_type": "jira",
                    "source_classification": "UNKNOWN",
                    "source_identifier": "GAP-1",
                    "confidence": 0.8,
                    "classification": "MISSING_INFORMATION",
                }
            ],
        }
    ]

    parsed = validate_structured_requirement_analysis(payload)
    assert len(parsed.assumptions) == 1
    assert len(parsed.missing_information) == 1


def test_schema_requires_provenance_classification_fields_when_present() -> None:
    payload = _minimal_payload()
    payload["business_goal"][0]["provenance"] = [
        {
            "source_type": "jira",
            "source_classification": "JIRA_ACCEPTANCE_CRITERIA",
            "source_location": "AC#2",
            "confidence": 0.9,
            "classification": "EXPLICIT",
        }
    ]

    parsed = validate_structured_requirement_analysis(payload)
    assert parsed.business_goal[0].provenance[0].source_classification.value == "JIRA_ACCEPTANCE_CRITERIA"
