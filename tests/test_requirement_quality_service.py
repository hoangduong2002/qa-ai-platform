from __future__ import annotations

import json
from pathlib import Path

from app.services.requirement_quality.service import run_requirement_quality_gate


def _structured_payload() -> dict:
    return {
        "schema_version": "1.0",
        "business_goal": [],
        "actors": [
            {
                "text": "Finance officer creates payout",
                "provenance": [
                    {
                        "source_type": "jira",
                        "source_classification": "JIRA_DESCRIPTION",
                        "source_identifier": "DESC-1",
                        "confidence": 0.9,
                        "classification": "EXPLICIT",
                    }
                ],
            }
        ],
        "preconditions": [],
        "triggers": [],
        "business_rules": [
            {
                "text": "System calculates fee of 10 and stores it properly",
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
        "state_transitions": [
            {
                "text": "Request is approved",
                "provenance": [],
            }
        ],
        "permissions": [],
        "integrations": [
            {
                "text": "Call external API for payout",
                "provenance": [],
            }
        ],
        "non_functional_requirements": [
            {
                "text": "System must be stable",
                "provenance": [],
            }
        ],
        "out_of_scope": [],
        "ambiguities": [],
        "contradictions": [
            {
                "text": "Comment says approval optional but AC says required",
                "provenance": [],
            }
        ],
        "assumptions": [
            {
                "text": "User already exists",
                "provenance": [],
            }
        ],
        "missing_information": [
            {
                "text": "Missing payout currency",
                "provenance": [],
            }
        ],
        "source_references": [],
    }


def test_quality_gate_disabled_returns_no_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_ENABLED", "false")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_MODE", "warn")

    result = run_requirement_quality_gate(
        ticket_id="QOFF-1",
        structured_analysis=_structured_payload(),
    )

    assert result["enabled"] is False
    assert result["quality_report"] is None
    assert not (tmp_path / "requirements" / "QOFF-1" / "analysis" / "quality_report.json").exists()


def test_quality_gate_warn_writes_report_and_questions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_MODE", "warn")
    monkeypatch.setenv("REQUIREMENT_QUALITY_LLM_REVIEW_ENABLED", "false")

    result = run_requirement_quality_gate(
        ticket_id="QWARN-1",
        structured_analysis=_structured_payload(),
    )

    assert result["enabled"] is True
    assert result["blocking"] is False
    assert result["quality_report"]["schema_version"] == "1.0"
    assert result["quality_report"]["mode"] == "warn"
    assert len(result["quality_report"]["blocking_issues"]) >= 1
    assert len(result["quality_report"]["warnings"]) >= 1

    report_file = tmp_path / "requirements" / "QWARN-1" / "analysis" / "quality_report.json"
    questions_file = tmp_path / "requirements" / "QWARN-1" / "analysis" / "clarification_questions_v2.json"

    assert report_file.exists()
    assert questions_file.exists()

    report = json.loads(report_file.read_text(encoding="utf-8"))
    questions = json.loads(questions_file.read_text(encoding="utf-8"))

    assert report["score"] <= 100
    assert isinstance(questions.get("questions"), list)
    assert any(item.get("issue_id") for item in questions["questions"])


def test_quality_gate_block_mode_sets_blocking_when_blockers_exist(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_MODE", "block_on_critical")

    result = run_requirement_quality_gate(
        ticket_id="QBLOCK-1",
        structured_analysis=_structured_payload(),
    )

    assert result["enabled"] is True
    assert result["blocking"] is True
    assert len(result["quality_report"]["blocking_issues"]) > 0


def test_quality_gate_handles_malformed_structured_analysis(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_ENABLED", "true")
    monkeypatch.setenv("REQUIREMENT_QUALITY_GATE_MODE", "warn")

    result = run_requirement_quality_gate(
        ticket_id="QERR-1",
        structured_analysis={"unexpected": []},
    )

    assert result["enabled"] is True
    assert result["quality_report"] is None
    assert result["error"]
    assert (tmp_path / "requirements" / "QERR-1" / "analysis" / "quality_report_error.txt").exists()
