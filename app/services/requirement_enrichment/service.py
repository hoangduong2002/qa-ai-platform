from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm
from app.services.requirement_enrichment.config import enrichment_mode
from app.services.requirement_enrichment.models import (
    EnrichedAnalysisReport,
    EnrichedFact,
    EnrichedFactClassification,
    EnrichedSourceReference,
    EnrichmentApproval,
    EnrichmentConflict,
    EnrichmentMode,
    EnrichmentQuestion,
)
from app.utils.llm_json import parse_json
from app.utils.prompt_loader import load_prompt


_STRUCTURED_FIELDS = [
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
]


def _read_json(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _analysis_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "analysis"


def _knowledge_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "knowledge"


def _load_structured_analysis(ticket_id: str, state: dict) -> dict:
    value = state.get("structured_analysis")
    if isinstance(value, dict) and value:
        return value
    return _read_json(_analysis_dir(ticket_id) / "structured_analysis.json", {})


def _load_quality_report(ticket_id: str, state: dict) -> dict:
    value = state.get("quality_report")
    if isinstance(value, dict) and value:
        return value
    return _read_json(_analysis_dir(ticket_id) / "quality_report.json", {})


def _load_selected_references(ticket_id: str) -> list[dict]:
    return [
        item
        for item in _read_json(_knowledge_dir(ticket_id) / "selected_references.json", [])
        if isinstance(item, dict)
    ]


def _load_review_records(ticket_id: str) -> list[dict]:
    return [
        item
        for item in _read_json(_knowledge_dir(ticket_id) / "review_records.json", [])
        if isinstance(item, dict)
    ]


def _load_conflicts(ticket_id: str) -> list[dict]:
    return [
        item
        for item in _read_json(_knowledge_dir(ticket_id) / "conflicts.json", [])
        if isinstance(item, dict)
    ]


def _load_or_create_approval(ticket_id: str) -> dict:
    path = _analysis_dir(ticket_id) / "enrichment_approval.json"
    payload = _read_json(path, None)

    if isinstance(payload, dict):
        return EnrichmentApproval.model_validate(payload).model_dump(mode="json")

    created = EnrichmentApproval(ticket_id=ticket_id).model_dump(mode="json")
    _write_json(path, created)
    return created


def _source_refs_from_provenance(provenance: list[Any]) -> list[EnrichedSourceReference]:
    refs: list[EnrichedSourceReference] = []

    for ref in provenance:
        if not isinstance(ref, dict):
            continue

        refs.append(
            EnrichedSourceReference(
                source_type=str(ref.get("source_type") or "jira"),
                source_identifier=ref.get("source_identifier") or None,
                source_location=ref.get("source_location") or None,
                citation=ref.get("source_identifier") or ref.get("source_location") or None,
                source_excerpt=ref.get("source_excerpt") or None,
                reviewed_decision=None,
            )
        )

    return refs


def _jira_facts_from_structured(structured_analysis: dict) -> list[EnrichedFact]:
    facts: list[EnrichedFact] = []

    for field in _STRUCTURED_FIELDS:
        raw_items = structured_analysis.get(field, []) if isinstance(structured_analysis, dict) else []
        if not isinstance(raw_items, list):
            continue

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            statement = str(item.get("text") or "").strip()
            if not statement:
                continue

            confidence = item.get("confidence")
            try:
                confidence_value = float(confidence) if confidence is not None else 0.8
            except Exception:
                confidence_value = 0.8

            facts.append(
                EnrichedFact(
                    statement=statement,
                    classification=EnrichedFactClassification.JIRA_FACT,
                    source_references=_source_refs_from_provenance(item.get("provenance", [])),
                    confidence=max(0.0, min(1.0, confidence_value)),
                    effective_date=None,
                    affected_requirement_fields=[field],
                )
            )

    return _dedupe_facts(facts)


def _approved_reference_material(selected_references: list[dict], review_records: list[dict]) -> list[dict]:
    material: list[dict] = []

    for item in selected_references:
        row = dict(item)
        row["reviewed"] = True
        row["reviewed_decision"] = row.get("requested_decision") or "ACCEPT"
        material.append(row)

    for item in review_records:
        classification = str(item.get("classification") or "")
        if classification != "HISTORICAL_CONTEXT_ONLY":
            continue

        material.append(
            {
                **item,
                "reviewed": True,
                "reviewed_decision": item.get("requested_decision") or "MARK_HISTORICAL",
                "historical_only": True,
            }
        )

    # Deduplicate by source_result_id.
    deduped: list[dict] = []
    seen = set()
    for item in material:
        key = str(item.get("source_result_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _deterministic_knowledge_facts(approved_material: list[dict]) -> list[EnrichedFact]:
    facts: list[EnrichedFact] = []

    for item in approved_material:
        statement = str(item.get("excerpt") or "").strip()
        if not statement:
            continue

        source_type = str(item.get("source_type") or "UNKNOWN").upper()
        affected_fields = ["business_rules"]

        if source_type in {"DEFECT", "HISTORICAL_DEFECT"}:
            affected_fields = ["regression_risk"]
        elif source_type in {"TEST_CASE"}:
            affected_fields = ["coverage_guidance"]
        elif source_type in {"OBSERVED_BEHAVIOR", "UNKNOWN"}:
            affected_fields = ["observed_behavior"]

        refs = [
            EnrichedSourceReference(
                source_type="knowledge_base",
                source_identifier=str(item.get("source_result_id") or ""),
                source_location=str(item.get("collection_id") or ""),
                citation=str(item.get("citation") or ""),
                source_excerpt=statement,
                reviewed_decision=str(item.get("reviewed_decision") or ""),
            )
        ]

        confidence_raw = item.get("confidence")
        try:
            confidence_value = float(confidence_raw) if confidence_raw is not None else 0.7
        except Exception:
            confidence_value = 0.7

        facts.append(
            EnrichedFact(
                statement=statement,
                classification=EnrichedFactClassification.KB_REFERENCE,
                source_references=refs,
                confidence=max(0.0, min(1.0, confidence_value)),
                effective_date=item.get("effective_from") or None,
                affected_requirement_fields=affected_fields,
            )
        )

    return _dedupe_facts(facts)


def _qa_confirmed_facts(review_records: list[dict]) -> list[EnrichedFact]:
    facts: list[EnrichedFact] = []

    for item in review_records:
        if str(item.get("classification") or "") != "ACCEPTED":
            continue

        statement = str(item.get("decision_reason") or item.get("excerpt") or "").strip()
        if not statement:
            continue

        refs = [
            EnrichedSourceReference(
                source_type="qa_review",
                source_identifier=str(item.get("source_result_id") or ""),
                source_location=str(item.get("reviewed_by") or ""),
                citation=str(item.get("citation") or ""),
                source_excerpt=str(item.get("excerpt") or ""),
                reviewed_decision=str(item.get("requested_decision") or "ACCEPT"),
            )
        ]

        facts.append(
            EnrichedFact(
                statement=statement,
                classification=EnrichedFactClassification.QA_CONFIRMED,
                source_references=refs,
                confidence=0.95,
                effective_date=item.get("effective_from") or None,
                affected_requirement_fields=["business_rules"],
            )
        )

    return _dedupe_facts(facts)


def _quality_questions(quality_report: dict) -> list[EnrichmentQuestion]:
    rows: list[EnrichmentQuestion] = []

    for key in ["blocking_issues", "warnings", "missing_information"]:
        value = quality_report.get(key, []) if isinstance(quality_report, dict) else []
        if not isinstance(value, list):
            continue

        for item in value:
            if not isinstance(item, dict):
                continue

            question = str(item.get("proposed_question") or "").strip()
            if not question:
                continue

            rows.append(
                EnrichmentQuestion(
                    question=question,
                    source="quality_gate",
                    related_issue_id=str(item.get("issue_id") or "") or None,
                )
            )

    return rows


def _assumptions_from_structured(structured_analysis: dict) -> list[EnrichedFact]:
    assumptions = structured_analysis.get("assumptions", []) if isinstance(structured_analysis, dict) else []
    rows: list[EnrichedFact] = []

    if not isinstance(assumptions, list):
        return rows

    for item in assumptions:
        if not isinstance(item, dict):
            continue

        statement = str(item.get("text") or "").strip()
        if not statement:
            continue

        confidence_raw = item.get("confidence")
        try:
            confidence_value = float(confidence_raw) if confidence_raw is not None else 0.5
        except Exception:
            confidence_value = 0.5

        rows.append(
            EnrichedFact(
                statement=statement,
                classification=EnrichedFactClassification.ASSUMPTION,
                source_references=_source_refs_from_provenance(item.get("provenance", [])),
                confidence=max(0.0, min(1.0, confidence_value)),
                effective_date=None,
                affected_requirement_fields=["assumptions"],
            )
        )

    return _dedupe_facts(rows)


def _rejected_candidate_facts(review_records: list[dict]) -> list[EnrichedFact]:
    rejected_classes = {"REJECTED", "OUTDATED", "CONFLICT", "NEEDS_CONFIRMATION"}
    rows: list[EnrichedFact] = []

    for item in review_records:
        if str(item.get("classification") or "") not in rejected_classes:
            continue

        statement = str(item.get("excerpt") or "").strip()
        if not statement:
            continue

        decision = str(item.get("requested_decision") or "")
        reason = str(item.get("decision_reason") or "").strip()
        rendered = statement if not reason else f"{statement} [rejected_reason: {reason}]"

        refs = [
            EnrichedSourceReference(
                source_type="knowledge_base",
                source_identifier=str(item.get("source_result_id") or ""),
                source_location=str(item.get("collection_id") or ""),
                citation=str(item.get("citation") or ""),
                source_excerpt=statement,
                reviewed_decision=decision,
            )
        ]

        rows.append(
            EnrichedFact(
                statement=rendered,
                classification=EnrichedFactClassification.KB_REFERENCE,
                source_references=refs,
                confidence=0.3,
                effective_date=item.get("effective_from") or None,
                affected_requirement_fields=["rejected_candidate_facts"],
            )
        )

    return _dedupe_facts(rows)


def _to_conflicts(conflicts: list[dict]) -> list[EnrichmentConflict]:
    rows: list[EnrichmentConflict] = []

    for item in conflicts:
        try:
            rows.append(
                EnrichmentConflict(
                    conflict_id=str(item.get("conflict_id") or ""),
                    conflict_type=str(item.get("conflict_type") or "UNKNOWN"),
                    severity=str(item.get("severity") or "MEDIUM"),
                    jira_source=item.get("jira_source") or None,
                    kb_source=item.get("kb_source") or None,
                    recommended_action=item.get("recommended_action") or None,
                )
            )
        except Exception:
            continue

    return rows


def _dedupe_facts(facts: list[EnrichedFact]) -> list[EnrichedFact]:
    deduped: list[EnrichedFact] = []
    seen = set()

    for fact in facts:
        key = (
            fact.classification.value,
            fact.statement.strip().lower(),
            "|".join(sorted((ref.citation or "") for ref in fact.source_references)),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(fact)

    return deduped


def _llm_prompt(
    *,
    jira_facts: list[dict],
    approved_reference_material: list[dict],
    conflicts: list[dict],
    unresolved_questions: list[dict],
    forbidden_assumptions: list[dict],
) -> str:
    template = load_prompt("prompts/enrich_requirement_analysis.md")

    return (
        template
        .replace("{authoritative_jira_facts}", json.dumps(jira_facts, indent=2, ensure_ascii=False))
        .replace("{approved_reference_material}", json.dumps(approved_reference_material, indent=2, ensure_ascii=False))
        .replace("{known_conflicts}", json.dumps(conflicts, indent=2, ensure_ascii=False))
        .replace("{unresolved_questions}", json.dumps(unresolved_questions, indent=2, ensure_ascii=False))
        .replace("{forbidden_assumptions}", json.dumps(forbidden_assumptions, indent=2, ensure_ascii=False))
    )


def _normalize_llm_fact(item: dict, classification: EnrichedFactClassification) -> EnrichedFact | None:
    if not isinstance(item, dict):
        return None

    statement = str(item.get("statement") or "").strip()
    if not statement:
        return None

    refs_raw = item.get("source_references", [])
    refs: list[EnrichedSourceReference] = []
    if isinstance(refs_raw, list):
        for ref in refs_raw:
            if not isinstance(ref, dict):
                continue
            refs.append(
                EnrichedSourceReference(
                    source_type=str(ref.get("source_type") or "unknown"),
                    source_identifier=ref.get("source_identifier") or None,
                    source_location=ref.get("source_location") or None,
                    citation=ref.get("citation") or None,
                    source_excerpt=ref.get("source_excerpt") or None,
                    reviewed_decision=ref.get("reviewed_decision") or None,
                )
            )

    confidence_raw = item.get("confidence")
    try:
        confidence_value = float(confidence_raw) if confidence_raw is not None else 0.5
    except Exception:
        confidence_value = 0.5

    fields_raw = item.get("affected_requirement_fields", [])
    fields = [str(entry).strip() for entry in fields_raw] if isinstance(fields_raw, list) else []
    fields = [entry for entry in fields if entry]

    # Enforce source separation: KB_REFERENCE must never be relabeled as JIRA_FACT.
    if classification == EnrichedFactClassification.JIRA_FACT:
        classification = EnrichedFactClassification.KB_REFERENCE

    return EnrichedFact(
        statement=statement,
        classification=classification,
        source_references=refs,
        confidence=max(0.0, min(1.0, confidence_value)),
        effective_date=item.get("effective_date") or None,
        affected_requirement_fields=fields,
    )


def _llm_enrichment(
    *,
    ai_mode: str | None,
    source_channel: str | None,
    jira_facts: list[EnrichedFact],
    approved_reference_material: list[dict],
    conflicts: list[EnrichmentConflict],
    unresolved_questions: list[EnrichmentQuestion],
    forbidden_assumptions: list[EnrichedFact],
) -> dict:
    if not approved_reference_material:
        return {
            "knowledge_supported_facts": [],
            "qa_confirmed_facts": [],
            "unresolved_questions": [],
            "assumptions": [],
            "rejected_candidate_facts": [],
        }

    prompt = _llm_prompt(
        jira_facts=[item.model_dump(mode="json") for item in jira_facts],
        approved_reference_material=approved_reference_material,
        conflicts=[item.model_dump(mode="json") for item in conflicts],
        unresolved_questions=[item.model_dump(mode="json") for item in unresolved_questions],
        forbidden_assumptions=[item.model_dump(mode="json") for item in forbidden_assumptions],
    )

    content = call_text_llm(
        task_type=TASK_REQUIREMENT_ANALYSIS,
        prompt=prompt,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )

    payload = parse_json(content, label="requirement enrichment response")
    if not isinstance(payload, dict):
        return {}

    return payload


def _evaluation_metrics(report: EnrichedAnalysisReport, review_records: list[dict]) -> dict:
    knowledge_and_qa = report.knowledge_supported_facts + report.qa_confirmed_facts
    all_non_jira = knowledge_and_qa + report.rejected_candidate_facts

    missing_citation_count = 0
    for fact in all_non_jira:
        has_citation = any((ref.citation or "").strip() for ref in fact.source_references)
        if not has_citation:
            missing_citation_count += 1

    missing_citation_rate = missing_citation_count / len(all_non_jira) if all_non_jira else 0.0

    unsupported_count = len(
        [
            fact
            for fact in report.knowledge_supported_facts
            if not fact.source_references or not any((ref.citation or "").strip() for ref in fact.source_references)
        ]
    )
    unsupported_fact_rate = unsupported_count / len(report.knowledge_supported_facts) if report.knowledge_supported_facts else 0.0

    contradiction_types = {"CONTRADICTS_JIRA", "DATE_MISMATCH", "VALUE_MISMATCH", "STATUS_MISMATCH"}
    contradiction_count = len([item for item in report.conflicts if item.conflict_type in contradiction_types])
    jira_contradiction_rate = contradiction_count / len(report.knowledge_supported_facts) if report.knowledge_supported_facts else 0.0

    reviewed_count = len([item for item in review_records if isinstance(item, dict)])
    accepted_count = len([item for item in review_records if str(item.get("classification") or "") == "ACCEPTED"])
    rejected_count = len([item for item in review_records if str(item.get("classification") or "") in {"REJECTED", "OUTDATED", "CONFLICT", "NEEDS_CONFIRMATION"}])

    useful_enrichment_acceptance_rate = accepted_count / reviewed_count if reviewed_count else 0.0
    rejected_enrichment_rate = rejected_count / reviewed_count if reviewed_count else 0.0

    assumption_rate = len(report.assumptions) / (
        len(report.jira_derived_facts)
        + len(report.knowledge_supported_facts)
        + len(report.qa_confirmed_facts)
        + len(report.assumptions)
    ) if (len(report.jira_derived_facts) + len(report.knowledge_supported_facts) + len(report.qa_confirmed_facts) + len(report.assumptions)) else 0.0

    critical_business_rule_coverage = 1.0 if any(
        "business_rules" in fact.affected_requirement_fields
        for fact in (report.knowledge_supported_facts + report.qa_confirmed_facts)
    ) else 0.0

    return {
        "unsupported_fact_rate": round(unsupported_fact_rate, 4),
        "jira_contradiction_rate": round(jira_contradiction_rate, 4),
        "useful_enrichment_acceptance_rate": round(useful_enrichment_acceptance_rate, 4),
        "rejected_enrichment_rate": round(rejected_enrichment_rate, 4),
        "missing_citation_rate": round(missing_citation_rate, 4),
        "assumption_rate": round(assumption_rate, 4),
        "critical_business_rule_coverage": round(critical_business_rule_coverage, 4),
    }


def _build_diff(report: EnrichedAnalysisReport) -> dict:
    jira_statements = [item.statement for item in report.jira_derived_facts]
    jira_set = {item.strip().lower() for item in jira_statements}

    added_kb = [
        item.statement
        for item in report.knowledge_supported_facts
        if item.statement.strip().lower() not in jira_set
    ]

    return {
        "schema_version": "1.0",
        "unchanged_jira_facts": jira_statements,
        "added_kb_supported_facts": added_kb,
        "unresolved_conflicts": [item.model_dump(mode="json") for item in report.conflicts],
        "new_questions": [item.model_dump(mode="json") for item in report.unresolved_questions],
        "assumptions": [item.model_dump(mode="json") for item in report.assumptions],
    }


def run_requirement_enrichment(state: dict) -> dict:
    mode = enrichment_mode()

    if mode == EnrichmentMode.OFF:
        return {
            "enrichment": {
                "enabled": False,
                "mode": mode.value,
                "active_for_downstream": False,
            }
        }

    ticket_id = str(state.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("ticket_id is required for enrichment")

    structured_analysis = _load_structured_analysis(ticket_id, state)
    quality_report = _load_quality_report(ticket_id, state)
    selected_references = _load_selected_references(ticket_id)
    review_records = _load_review_records(ticket_id)
    known_conflicts_raw = _load_conflicts(ticket_id)

    approval = _load_or_create_approval(ticket_id)

    jira_facts = _jira_facts_from_structured(structured_analysis)
    approved_material = _approved_reference_material(selected_references, review_records)
    deterministic_knowledge = _deterministic_knowledge_facts(approved_material)
    qa_confirmed = _qa_confirmed_facts(review_records)
    unresolved_questions = _quality_questions(quality_report)
    assumptions = _assumptions_from_structured(structured_analysis)
    rejected_candidates = _rejected_candidate_facts(review_records)
    known_conflicts = _to_conflicts(known_conflicts_raw)

    llm_payload = {}
    try:
        llm_payload = _llm_enrichment(
            ai_mode=state.get("ai_mode"),
            source_channel=state.get("source_channel"),
            jira_facts=jira_facts,
            approved_reference_material=approved_material,
            conflicts=known_conflicts,
            unresolved_questions=unresolved_questions,
            forbidden_assumptions=assumptions,
        )
    except Exception:
        llm_payload = {}

    llm_knowledge = []
    for item in llm_payload.get("knowledge_supported_facts", []) if isinstance(llm_payload, dict) else []:
        normalized = _normalize_llm_fact(item, EnrichedFactClassification.KB_REFERENCE)
        if normalized:
            llm_knowledge.append(normalized)

    llm_qa_confirmed = []
    for item in llm_payload.get("qa_confirmed_facts", []) if isinstance(llm_payload, dict) else []:
        normalized = _normalize_llm_fact(item, EnrichedFactClassification.QA_CONFIRMED)
        if normalized:
            llm_qa_confirmed.append(normalized)

    llm_assumptions = []
    for item in llm_payload.get("assumptions", []) if isinstance(llm_payload, dict) else []:
        normalized = _normalize_llm_fact(item, EnrichedFactClassification.ASSUMPTION)
        if normalized:
            llm_assumptions.append(normalized)

    llm_rejected = []
    for item in llm_payload.get("rejected_candidate_facts", []) if isinstance(llm_payload, dict) else []:
        normalized = _normalize_llm_fact(item, EnrichedFactClassification.KB_REFERENCE)
        if normalized:
            llm_rejected.append(normalized)

    llm_questions = []
    for item in llm_payload.get("unresolved_questions", []) if isinstance(llm_payload, dict) else []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        llm_questions.append(
            EnrichmentQuestion(
                question=question,
                source="enrichment_llm",
                related_issue_id=str(item.get("related_issue_id") or "") or None,
            )
        )

    knowledge_supported = _dedupe_facts(deterministic_knowledge + llm_knowledge)
    qa_confirmed_facts = _dedupe_facts(qa_confirmed + llm_qa_confirmed)
    assumption_facts = _dedupe_facts(assumptions + llm_assumptions)
    rejected_facts = _dedupe_facts(rejected_candidates + llm_rejected)
    merged_questions = unresolved_questions + llm_questions

    active_for_downstream = False
    if mode == EnrichmentMode.AUTOMATIC:
        active_for_downstream = True
    elif mode == EnrichmentMode.MANUAL:
        active_for_downstream = bool(approval.get("approved", False))

    report = EnrichedAnalysisReport(
        mode=mode,
        active_for_downstream=active_for_downstream,
        jira_derived_facts=jira_facts,
        knowledge_supported_facts=knowledge_supported,
        qa_confirmed_facts=qa_confirmed_facts,
        unresolved_questions=merged_questions,
        conflicts=known_conflicts,
        assumptions=assumption_facts,
        rejected_candidate_facts=rejected_facts,
    )
    report.evaluation_metrics = _evaluation_metrics(report, review_records)

    diff = _build_diff(report)

    report_payload = report.model_dump(mode="json")
    diff_payload = diff

    _write_json(_analysis_dir(ticket_id) / "enriched_analysis.json", report_payload)
    _write_json(_analysis_dir(ticket_id) / "enrichment_diff.json", diff_payload)
    _write_json(_analysis_dir(ticket_id) / "enrichment_approval.json", approval)

    return {
        "enrichment": {
            "enabled": True,
            "mode": mode.value,
            "active_for_downstream": active_for_downstream,
            "approval_required": mode == EnrichmentMode.MANUAL,
        },
        "enriched_analysis": report_payload,
        "enrichment_diff": diff_payload,
        "enrichment_approval": approval,
        "active_enriched_analysis": report_payload if active_for_downstream else None,
    }
