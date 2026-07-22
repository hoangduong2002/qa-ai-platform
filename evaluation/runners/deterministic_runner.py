from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.quality_feedback.versions import model_configuration, prompt_versions
from evaluation.metrics.deterministic import calculate_aggregate_metrics, calculate_ticket_metrics
from evaluation.schemas.golden_dataset import GoldenDataset, GoldenTicket


def _fixture_metrics(ticket: GoldenTicket) -> dict[str, Any]:
    structured = {
        "schema_version": "1.0",
        "business_rules": [{"text": text, "provenance": [{"source_classification": "JIRA", "confidence": 1.0, "classification": "AUTHORITATIVE", "source_identifier": ticket.ticket_id}]} for text in ticket.expected_business_rules],
        "expected_results": [{"text": text, "provenance": [{"source_classification": "JIRA", "confidence": 1.0, "classification": "AUTHORITATIVE", "source_identifier": ticket.ticket_id}]} for text in ticket.expected_results],
        "missing_information": [{"text": text, "provenance": [{"source_classification": "JIRA", "confidence": 1.0, "classification": "AUTHORITATIVE", "source_identifier": ticket.ticket_id}]} for text in ticket.expected_missing_information],
        "ambiguities": [{"text": text, "provenance": [{"source_classification": "JIRA", "confidence": 1.0, "classification": "AUTHORITATIVE", "source_identifier": ticket.ticket_id}]} for text in ticket.expected_ambiguities],
        "contradictions": [{"text": text, "provenance": [{"source_classification": "JIRA", "confidence": 1.0, "classification": "AUTHORITATIVE", "source_identifier": ticket.ticket_id}]} for text in ticket.expected_contradictions],
        "assumptions": [],
    }
    scenarios = [
        {"title": text}
        for text in ticket.critical_scenarios + ticket.expected_acceptance_criteria_coverage.required_items
    ]
    testcases = [
        {"test_case": text, "precondition": "Fixture precondition", "steps": "Execute fixture action", "expected_result": "Fixture result"}
        for text in ticket.critical_test_cases
    ]
    return calculate_ticket_metrics(
        expected_business_rules=ticket.expected_business_rules,
        expected_results=ticket.expected_results,
        critical_scenarios=ticket.critical_scenarios,
        critical_test_cases=ticket.critical_test_cases,
        expected_missing_information=ticket.expected_missing_information,
        expected_contradictions=ticket.expected_contradictions,
        expected_ambiguities=ticket.expected_ambiguities,
        acceptance_criteria_required_items=ticket.expected_acceptance_criteria_coverage.required_items,
        forbidden_assumptions=ticket.forbidden_assumptions,
        analysis={"requirement_items": [{"description": text} for text in ticket.expected_business_rules]},
        structured_analysis=structured,
        scenarios=scenarios,
        testcases=testcases,
        workflow_failed=False,
        expected_reference_ids=ticket.expected_reference_ids,
        retrieved_reference_ids=ticket.expected_reference_ids,
        expected_exact_codes=ticket.expected_exact_codes,
        retrieved_exact_codes=ticket.expected_exact_codes,
    )


class DeterministicEvaluationRunner:
    """Evaluates checked-in fixtures only; it never imports credentials or calls an LLM."""

    def run_dataset(self, dataset: GoldenDataset, run_id: str, ticket_filter: str | None = None, domain_filter: str | None = None) -> dict[str, Any]:
        selected = [
            ticket for ticket in dataset.tickets
            if (ticket_filter is None or ticket.ticket_id == ticket_filter)
            and (domain_filter is None or ticket.domain == domain_filter)
        ]
        if (ticket_filter or domain_filter) and not selected:
            raise ValueError("No golden tickets matched the requested filter.")
        tickets = [
            {"ticket_id": item.ticket_id, "domain": item.domain, "success": True, "error": None, "duration_seconds": 0.0, "metrics": _fixture_metrics(item), "model_metadata": {"model_identifiers": [], "prompt_identifiers": prompt_versions()}}
            for item in selected
        ]
        per_domain: dict[str, Any] = {}
        for domain in sorted({item["domain"] for item in tickets}):
            per_domain[domain] = calculate_aggregate_metrics([item["metrics"] for item in tickets if item["domain"] == domain])
        return {
            "report_schema_version": "2.0",
            "run_id": run_id,
            "execution_mode": "deterministic",
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.dataset_version,
            "generated_at": datetime.now().astimezone().isoformat(),
            "versions": {"dataset": dataset.dataset_version, "prompt_versions": prompt_versions(), "model_identifiers": [], "model_configuration": {"execution": "deterministic", **model_configuration()}, "analyzer": "structured-analysis-v1", "generator": "fixture", "reviewer": "fixture", "retrieval": "retrieval-v1", "ranking": "ranking-v1"},
            "tickets": tickets,
            "aggregate_metrics": calculate_aggregate_metrics([item["metrics"] for item in tickets]),
            "per_domain_metrics": per_domain,
            "detected_regressions": [],
            "execution_errors": [],
        }
