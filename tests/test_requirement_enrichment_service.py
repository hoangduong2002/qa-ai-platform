from __future__ import annotations

import json
from pathlib import Path

from app.services.requirement_enrichment.service import run_requirement_enrichment


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _base_state(ticket_id: str) -> dict:
    return {
        "ticket_id": ticket_id,
        "structured_analysis": {
            "schema_version": "1.0",
            "business_rules": [
                {
                    "text": "Fee is required",
                    "confidence": 0.9,
                    "provenance": [
                        {
                            "source_type": "jira",
                            "source_classification": "JIRA_DESCRIPTION",
                            "source_identifier": "DESC-1",
                            "source_excerpt": "Fee is required",
                        }
                    ],
                }
            ],
            "assumptions": [
                {
                    "text": "Legacy region behavior still applies",
                    "confidence": 0.4,
                    "provenance": [],
                }
            ],
        },
        "quality_report": {
            "blocking_issues": [],
            "warnings": [
                {
                    "issue_id": "QG-1",
                    "proposed_question": "What is the fee rounding rule?",
                }
            ],
            "missing_information": [],
        },
    }


def _seed_knowledge(ticket_id: str, *, selected: list[dict] | None = None, records: list[dict] | None = None, conflicts: list[dict] | None = None) -> None:
    base = Path("requirements") / ticket_id / "knowledge"
    _write_json(base / "selected_references.json", selected or [])
    _write_json(base / "review_records.json", records or [])
    _write_json(base / "conflicts.json", conflicts or [])


def test_no_accepted_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")

    _seed_knowledge("E1")

    result = run_requirement_enrichment(_base_state("E1"))

    assert result["enrichment"]["enabled"] is True
    assert result["enrichment"]["active_for_downstream"] is False
    assert result["enriched_analysis"]["knowledge_supported_facts"] == []


def test_accepted_official_rule(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")
    monkeypatch.setattr(
        "app.services.requirement_enrichment.service.call_text_llm",
        lambda *args, **kwargs: "{}",
    )

    _seed_knowledge(
        "E2",
        selected=[
            {
                "source_result_id": "DOC-1:v1:chunk1",
                "excerpt": "Fee rounding is half-up to 2 decimals.",
                "citation": "DOC-1:v1:chunk1",
                "confidence": 0.88,
                "source_type": "BUSINESS_RULE",
                "collection_id": "business-rules",
                "effective_from": "2026-01-01",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E2"))
    facts = result["enriched_analysis"]["knowledge_supported_facts"]

    assert len(facts) == 1
    assert facts[0]["classification"] == "KB_REFERENCE"
    assert "business_rules" in facts[0]["affected_requirement_fields"]


def test_historical_defect_is_regression_risk_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")
    monkeypatch.setattr(
        "app.services.requirement_enrichment.service.call_text_llm",
        lambda *args, **kwargs: "{}",
    )

    _seed_knowledge(
        "E3",
        records=[
            {
                "source_result_id": "BUG-1:v1:chunk1",
                "classification": "HISTORICAL_CONTEXT_ONLY",
                "requested_decision": "MARK_HISTORICAL",
                "excerpt": "Past defect: fee was skipped when retries occurred.",
                "citation": "BUG-1:v1:chunk1",
                "confidence": 0.7,
                "source_type": "DEFECT",
                "collection_id": "historical-defect",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E3"))
    facts = result["enriched_analysis"]["knowledge_supported_facts"]

    assert len(facts) == 1
    assert facts[0]["affected_requirement_fields"] == ["regression_risk"]


def test_jira_and_kb_conflict_preserved_unresolved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")

    _seed_knowledge(
        "E4",
        conflicts=[
            {
                "conflict_id": "CF-1",
                "conflict_type": "CONTRADICTS_JIRA",
                "severity": "CRITICAL",
                "jira_source": "source/description.md",
                "kb_source": "DOC-1:v1:chunk1",
                "recommended_action": "Manual QA confirmation required",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E4"))
    assert result["enriched_analysis"]["conflicts"][0]["conflict_type"] == "CONTRADICTS_JIRA"


def test_unsupported_value_and_missing_citation_metric(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")
    monkeypatch.setattr(
        "app.services.requirement_enrichment.service.call_text_llm",
        lambda *args, **kwargs: "{}",
    )

    _seed_knowledge(
        "E5",
        selected=[
            {
                "source_result_id": "DOC-2:v1:chunk1",
                "excerpt": "Fee is TBD.",
                "citation": "",
                "confidence": 0.5,
                "source_type": "BUSINESS_RULE",
                "collection_id": "business-rules",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E5"))
    metrics = result["enriched_analysis"]["evaluation_metrics"]

    assert metrics["missing_citation_rate"] > 0
    assert metrics["unsupported_fact_rate"] > 0


def test_shadow_isolation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")

    _seed_knowledge("E6")
    result = run_requirement_enrichment(_base_state("E6"))

    assert result["enrichment"]["mode"] == "shadow"
    assert result["active_enriched_analysis"] is None


def test_manual_mode_requires_ticket_approval(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "manual")

    _seed_knowledge("E7")

    first = run_requirement_enrichment(_base_state("E7"))
    assert first["enrichment"]["active_for_downstream"] is False

    _write_json(
        Path("requirements") / "E7" / "analysis" / "enrichment_approval.json",
        {
            "schema_version": "1.0",
            "ticket_id": "E7",
            "approved": True,
            "approved_by": "qa.reviewer",
            "approved_at": "2026-07-22T00:00:00Z",
            "note": "approved",
        },
    )

    second = run_requirement_enrichment(_base_state("E7"))
    assert second["enrichment"]["active_for_downstream"] is True
    assert isinstance(second["active_enriched_analysis"], dict)


def test_rejected_enrichment_is_separated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")

    _seed_knowledge(
        "E8",
        records=[
            {
                "source_result_id": "DOC-BAD:v1:chunk1",
                "classification": "REJECTED",
                "requested_decision": "REJECT",
                "decision_reason": "Contradicts Jira",
                "excerpt": "Fee is optional.",
                "citation": "DOC-BAD:v1:chunk1",
                "source_type": "OBSERVED_BEHAVIOR",
                "collection_id": "observed-behavior",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E8"))
    rejected = result["enriched_analysis"]["rejected_candidate_facts"]

    assert len(rejected) == 1
    assert rejected[0]["classification"] == "KB_REFERENCE"


def test_source_classifications_are_preserved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "shadow")
    monkeypatch.setattr(
        "app.services.requirement_enrichment.service.call_text_llm",
        lambda *args, **kwargs: "{}",
    )

    _seed_knowledge(
        "E9",
        selected=[
            {
                "source_result_id": "DOC-OK:v1:chunk1",
                "excerpt": "Fee policy explicitly defines half-up rounding.",
                "citation": "DOC-OK:v1:chunk1",
                "confidence": 0.9,
                "source_type": "BUSINESS_RULE",
                "collection_id": "business-rules",
            }
        ],
        records=[
            {
                "source_result_id": "DOC-OK:v1:chunk1",
                "classification": "ACCEPTED",
                "requested_decision": "ACCEPT",
                "decision_reason": "Matches Jira",
                "excerpt": "Fee policy explicitly defines half-up rounding.",
                "citation": "DOC-OK:v1:chunk1",
                "source_type": "BUSINESS_RULE",
                "collection_id": "business-rules",
                "reviewed_by": "qa.reviewer",
            }
        ],
    )

    result = run_requirement_enrichment(_base_state("E9"))["enriched_analysis"]

    assert all(item["classification"] == "JIRA_FACT" for item in result["jira_derived_facts"])
    assert all(item["classification"] == "KB_REFERENCE" for item in result["knowledge_supported_facts"])
    assert all(item["classification"] == "QA_CONFIRMED" for item in result["qa_confirmed_facts"])
    assert all(item["classification"] == "ASSUMPTION" for item in result["assumptions"])


def test_feature_rollback_off_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_ANALYSIS_ENRICHMENT_MODE", "off")

    _seed_knowledge("E10")
    result = run_requirement_enrichment(_base_state("E10"))

    assert result["enrichment"]["enabled"] is False
    assert not (Path("requirements") / "E10" / "analysis" / "enriched_analysis.json").exists()
