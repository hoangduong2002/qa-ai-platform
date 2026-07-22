from __future__ import annotations

import json
from pathlib import Path

from graph.nodes.analyze_requirement import analyze_requirement
from app.services.structured_requirement_analysis_service import run_structured_requirement_analysis_shadow


def _authoritative_analysis_json() -> str:
    return json.dumps(
        {
            "actors": ["Shopper"],
            "functional_requirements": ["Block submission with missing required fields"],
            "business_rules": ["Shipping address is required"],
            "validations": ["Display field-level error messages"],
            "dependencies": [],
            "risks": [],
            "missing_information": ["Payment method scope"],
            "requirement_items": [
                {
                    "requirement_id": "FR001",
                    "type": "Functional Requirement",
                    "description": "Block submission with missing required fields",
                }
            ],
        }
    )


def _structured_json() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "business_goal": [
                {
                    "fact_id": "BG-1",
                    "text": "Prevent invalid checkout submissions",
                    "confidence": 0.9,
                    "classification": "EXPLICIT",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_DESCRIPTION",
                            "source_identifier": "DESC-1",
                            "source_excerpt": "must not submit checkout",
                            "confidence": 0.9,
                            "classification": "EXPLICIT",
                        }
                    ],
                }
            ],
            "actors": [],
            "preconditions": [],
            "triggers": [],
            "business_rules": [
                {
                    "text": "Shipping address is mandatory",
                    "confidence": 0.9,
                    "classification": "EXPLICIT",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_ACCEPTANCE_CRITERIA",
                            "source_identifier": "AC-1",
                            "confidence": 0.9,
                            "classification": "EXPLICIT",
                        }
                    ],
                }
            ],
            "input_data": [],
            "expected_results": [],
            "error_behaviors": [],
            "state_transitions": [],
            "permissions": [],
            "integrations": [],
            "non_functional_requirements": [],
            "out_of_scope": [],
            "ambiguities": [
                {
                    "text": "Region-specific required fields are unclear",
                    "confidence": 0.6,
                    "classification": "AMBIGUOUS",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_COMMENT",
                            "source_identifier": "COMMENT-1",
                            "confidence": 0.6,
                            "classification": "AMBIGUOUS",
                        }
                    ],
                }
            ],
            "contradictions": [
                {
                    "text": "Description and comments conflict on whether address is optional",
                    "confidence": 0.8,
                    "classification": "CONTRADICTION",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_DESCRIPTION",
                            "source_identifier": "DESC-1",
                            "confidence": 0.8,
                            "classification": "CONTRADICTION",
                        }
                    ],
                }
            ],
            "assumptions": [
                {
                    "text": "Guest checkout is enabled",
                    "confidence": 0.3,
                    "classification": "ASSUMPTION",
                    "provenance": [],
                }
            ],
            "missing_information": [
                {
                    "text": "Payment method support matrix is missing",
                    "confidence": 0.9,
                    "classification": "MISSING_INFORMATION",
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "UNKNOWN",
                            "source_identifier": "GAP-1",
                            "confidence": 0.9,
                            "classification": "MISSING_INFORMATION",
                        }
                    ],
                }
            ],
            "source_references": [],
        }
    )


def test_shadow_disabled_skips_artifact_and_call(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "false")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")

    def _fail(*args, **kwargs):
        raise AssertionError("LLM must not be called when flag is disabled")

    monkeypatch.setattr("app.services.structured_requirement_analysis_service.call_text_llm", _fail)

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T1",
            "requirement_context": "Summary: ...",
        }
    )

    assert result == {}
    assert not (tmp_path / "requirements" / "T1" / "analysis" / "structured_analysis.json").exists()


def test_shadow_mode_false_promotes_structured_analysis(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "false")

    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.call_text_llm",
        lambda *args, **kwargs: _structured_json(),
    )

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T2",
            "requirement_context": "Summary: ...",
        }
    )

    assert result["structured_analysis"]["schema_version"] == "1.0"
    assert result["structured_analysis_metadata"]["shadow_mode"] is False
    assert result["structured_analysis_metadata"]["active_for_downstream"] is True


def test_shadow_model_failure_does_not_raise(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.services.structured_requirement_analysis_service.call_text_llm", _raise)

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T3",
            "requirement_context": "Summary: ...",
            "ai_mode": "TEST_LOCAL_ONLY",
        }
    )

    assert "structured_analysis_error" in result
    assert (tmp_path / "requirements" / "T3" / "analysis" / "structured_analysis_error.txt").exists()


def test_shadow_malformed_model_output_records_parse_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )

    calls = {"n": 0}

    def _bad(*args, **kwargs):
        calls["n"] += 1
        return "not json"

    monkeypatch.setattr("app.services.structured_requirement_analysis_service.call_text_llm", _bad)

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T4",
            "requirement_context": "Summary: ...",
            "ai_mode": "TEST_LOCAL_ONLY",
        }
    )

    assert calls["n"] == 2
    assert "structured_analysis_error" in result
    assert (tmp_path / "requirements" / "T4" / "analysis" / "structured_analysis_parse_error.txt").exists()


def test_shadow_success_writes_structured_artifact_with_provenance(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )

    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.call_text_llm",
        lambda *args, **kwargs: _structured_json(),
    )

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T5",
            "requirement_context": "Summary: ...",
        }
    )

    assert "structured_analysis" in result
    saved = json.loads((tmp_path / "requirements" / "T5" / "analysis" / "structured_analysis.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0"
    assert saved["business_goal"][0]["provenance"][0]["source_classification"] == "JIRA_DESCRIPTION"


def test_existing_authoritative_output_equivalence_when_shadow_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )

    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.call_text_llm",
        lambda *args, **kwargs: _authoritative_analysis_json(),
    )
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.resolve_provider_for_task",
        lambda *_args, **_kwargs: {
            "provider": "TEST",
            "ai_mode": "TEST_LOCAL_ONLY",
            "model": "test-model",
        },
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.call_text_llm",
        lambda *args, **kwargs: _structured_json(),
    )

    state = {
        "ticket_id": "T6",
        "requirement_context": "Summary: Checkout",
        "requirement_context_metadata": {},
    }

    result = analyze_requirement(state)

    saved_analysis = json.loads((tmp_path / "requirements" / "T6" / "analysis" / "requirement_analysis.json").read_text(encoding="utf-8"))

    assert result["analysis"] == saved_analysis
    assert "structured_analysis" in result


def test_quality_gate_warn_mode_is_non_blocking(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_MODE", "warn")
    monkeypatch.setenv("REQUIREMENT_QUALITY_LLM_REVIEW_ENABLED", "false")

    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.call_text_llm",
        lambda *args, **kwargs: _authoritative_analysis_json(),
    )
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.resolve_provider_for_task",
        lambda *_args, **_kwargs: {
            "provider": "TEST",
            "ai_mode": "TEST_LOCAL_ONLY",
            "model": "test-model",
        },
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.call_text_llm",
        lambda *args, **kwargs: _structured_json(),
    )

    result = analyze_requirement(
        {
            "ticket_id": "T6Q",
            "requirement_context": "Summary: Checkout",
            "requirement_context_metadata": {},
        }
    )

    assert "analysis" in result
    assert result.get("quality_gate", {}).get("enabled") is True
    assert result.get("quality_gate", {}).get("mode") == "warn"
    assert result.get("quality_gate", {}).get("blocking") is False
    assert (tmp_path / "requirements" / "T6Q" / "analysis" / "quality_report.json").exists()
    assert (tmp_path / "requirements" / "T6Q" / "analysis" / "clarification_questions_v2.json").exists()


def test_existing_authoritative_path_unchanged_when_feature_off(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "false")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )

    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.call_text_llm",
        lambda *args, **kwargs: _authoritative_analysis_json(),
    )
    monkeypatch.setattr(
        "graph.nodes.analyze_requirement.resolve_provider_for_task",
        lambda *_args, **_kwargs: {
            "provider": "TEST",
            "ai_mode": "TEST_LOCAL_ONLY",
            "model": "test-model",
        },
    )

    state = {
        "ticket_id": "T6B",
        "requirement_context": "Summary: Checkout",
        "requirement_context_metadata": {},
    }

    result = analyze_requirement(state)

    assert "analysis" in result
    assert "structured_analysis" not in result
    assert not (tmp_path / "requirements" / "T6B" / "analysis" / "structured_analysis.json").exists()


def test_contradictory_and_ambiguous_facts_are_preserved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRUCTURED_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_ANALYSIS_SHADOW_MODE", "true")
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.load_prompt",
        lambda *_args, **_kwargs: "Requirement:\n{requirement_context}",
    )
    monkeypatch.setattr(
        "app.services.structured_requirement_analysis_service.call_text_llm",
        lambda *args, **kwargs: _structured_json(),
    )

    result = run_structured_requirement_analysis_shadow(
        {
            "ticket_id": "T7",
            "requirement_context": "Description conflicts with comments.",
        }
    )

    structured = result["structured_analysis"]
    assert len(structured["contradictions"]) >= 1
    assert len(structured["ambiguities"]) >= 1
