from __future__ import annotations

import json
from pathlib import Path

from app.utils.requirement_context_loader import load_requirement_context_for_llm


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return default


def _accepted_references(items) -> list[dict]:
    return [
        item
        for item in items or []
        if isinstance(item, dict)
        and str(item.get("classification") or "").upper() == "ACCEPTED"
    ]


def _unresolved_conflicts(items) -> list[dict]:
    resolved = {"RESOLVED", "ACCEPTED", "REJECTED", "CLOSED"}
    return [
        item
        for item in items or []
        if isinstance(item, dict)
        and str(item.get("status") or "OPEN").upper() not in resolved
        and item.get("resolved") is not True
    ]


def build_generator_v2_inputs(state: dict) -> dict:
    ticket_id = str(state.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("ticket_id is required for V2 test-case generation")

    root = Path("requirements") / ticket_id
    analysis_dir = root / "analysis"
    knowledge_dir = root / "knowledge"
    design_dir = root / "test-design"

    jira_source = state.get("requirement_context")
    if not jira_source:
        jira_source, _ = load_requirement_context_for_llm(ticket_id)

    structured_analysis = (
        state.get("structured_analysis")
        or _read_json(analysis_dir / "structured_analysis.json", {})
    )
    enrichment_approval = (
        state.get("enrichment_approval")
        or _read_json(analysis_dir / "enrichment_approval.json", {})
    )
    enriched_analysis = (
        state.get("active_enriched_analysis")
        or state.get("enriched_analysis")
        or _read_json(analysis_dir / "enriched_analysis.json", {})
    )
    approved_analysis = (
        enriched_analysis
        if isinstance(enrichment_approval, dict)
        and enrichment_approval.get("approved") is True
        and isinstance(enriched_analysis, dict)
        else structured_analysis
    )

    selected_references = state.get("selected_references")
    if not isinstance(selected_references, list):
        selected_references = _read_json(
            knowledge_dir / "selected_references.json", []
        )
    accepted_references = _accepted_references(selected_references)

    conflicts = state.get("knowledge_conflicts")
    if not isinstance(conflicts, list):
        conflicts = _read_json(knowledge_dir / "conflicts.json", [])

    coverage_model = (
        state.get("coverage_model")
        or _read_json(design_dir / "coverage_model.json", {})
    )
    clarification_answers = (
        state.get("clarification_answers")
        or _read_json(analysis_dir / "clarification_answers.json", {})
    )
    quality_report = (
        state.get("quality_report")
        or _read_json(analysis_dir / "quality_report.json", {})
    )
    unresolved_issues = {
        "quality_blockers": (
            quality_report.get("blocking_issues", [])
            if isinstance(quality_report, dict) else []
        ),
        "analysis_questions": (
            approved_analysis.get("unresolved_questions", [])
            if isinstance(approved_analysis, dict) else []
        ),
        "coverage_questions": (
            coverage_model.get("uncovered_questions", [])
            if isinstance(coverage_model, dict) else []
        ),
    }

    return {
        "ticket_id": ticket_id,
        "authoritative_jira_source": jira_source or "",
        "approved_analysis": approved_analysis if isinstance(approved_analysis, dict) else {},
        "accepted_knowledge_references": accepted_references,
        "confirmed_clarifications": clarification_answers,
        "unresolved_conflicts": _unresolved_conflicts(conflicts),
        "unresolved_issues": unresolved_issues,
        "coverage_model": coverage_model if isinstance(coverage_model, dict) else {},
        "scenarios": [
            item for item in state.get("scenarios", []) if isinstance(item, dict)
        ],
        "test_scope_constraints": (
            state.get("test_scope") if isinstance(state.get("test_scope"), dict) else {}
        ),
        "output_format_constraints": {
            "schema_version": "2.0",
            "one_primary_action_per_step": True,
            "observable_expected_results": True,
            "explicit_test_data": True,
            "unsupported_values_forbidden": True,
            "preserve_out_of_scope_exclusions": True,
            "source_traceability_required": True,
        },
    }


def source_catalog(inputs: dict) -> dict[tuple[str, str], dict]:
    catalog: dict[tuple[str, str], dict] = {}
    ticket_id = str(inputs.get("ticket_id") or "")
    if inputs.get("authoritative_jira_source"):
        catalog[("JIRA", ticket_id)] = {"classification": "AUTHORITATIVE"}

    for source_id in (inputs.get("coverage_model") or {}).get("requirement_refs", []):
        clean_id = str(source_id or "").strip()
        if clean_id:
            catalog[("JIRA", clean_id)] = {"classification": "AUTHORITATIVE"}

    analysis = inputs.get("approved_analysis") or {}
    for section in (
        "functional_requirements",
        "business_rules",
        "validations",
        "integrations",
        "error_handling",
        "non_functional_requirements",
        "requirement_items",
    ):
        for item in analysis.get(section, []) if isinstance(analysis, dict) else []:
            if not isinstance(item, dict):
                continue
            source_id = str(
                item.get("id")
                or item.get("requirement_id")
                or item.get("statement_id")
                or ""
            ).strip()
            if source_id:
                catalog[("JIRA", source_id)] = {"classification": "AUTHORITATIVE"}

    for item in inputs.get("accepted_knowledge_references", []):
        source_id = str(
            item.get("source_result_id")
            or item.get("result_id")
            or item.get("citation")
            or ""
        ).strip()
        if not source_id:
            continue
        source_type = str(item.get("source_type") or "").upper()
        kind = "HISTORICAL_DEFECT" if source_type in {
            "DEFECT", "HISTORICAL_DEFECT", "HISTORICAL_DEFECTS"
        } else "KNOWLEDGE_BASE"
        catalog[(kind, source_id)] = {"classification": "ACCEPTED"}

    clarification_payload = inputs.get("confirmed_clarifications") or {}
    if isinstance(clarification_payload, dict):
        clarification_rows = next(
            (
                clarification_payload.get(key)
                for key in ("answers", "clarification_answers", "answered_clarifications")
                if isinstance(clarification_payload.get(key), list)
            ),
            [],
        )
    elif isinstance(clarification_payload, list):
        clarification_rows = clarification_payload
    else:
        clarification_rows = []
    for index, item in enumerate(clarification_rows, start=1):
        if not isinstance(item, dict):
            continue
        answer = item.get("answer") or item.get("response")
        if not str(answer or "").strip():
            continue
        source_id = str(
            item.get("question_id") or item.get("id") or f"clarification-{index}"
        )
        catalog[("CONFIRMED_CLARIFICATION", source_id)] = {
            "classification": "CONFIRMED"
        }

    return catalog
