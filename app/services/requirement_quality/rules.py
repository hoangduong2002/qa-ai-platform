from __future__ import annotations

import re
from collections import defaultdict

from app.services.requirement_quality.models import (
    QualityIssue,
    QualityIssueType,
    QualitySeverity,
    SourceReference,
)


VAGUE_TERMS_RE = re.compile(r"\b(correct|properly|normally|appropriate)\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|JPY|VND|\$|€|£)\b", re.IGNORECASE)
CALCULATION_RE = re.compile(r"\b(calculate|formula|percentage|percent|sum|total)\b", re.IGNORECASE)
ROUNDING_RE = re.compile(r"\b(round|rounding|truncate|precision|decimal)\b", re.IGNORECASE)
DATE_DEPENDENT_RE = re.compile(r"\b(effective|from|to|until|before|after|date|daily|monthly|yearly)\b", re.IGNORECASE)
INTEGRATION_RE = re.compile(r"\b(api|service|endpoint|webhook|integration|third[ -]?party)\b", re.IGNORECASE)
TIMEOUT_RE = re.compile(r"\b(timeout|retry|latency|sla|failure|fallback|error)\b", re.IGNORECASE)
OBSERVABLE_RE = re.compile(r"\b(display|return|persist|emit|reject|allow|block|create|update|delete|status|response)\b", re.IGNORECASE)


def _to_refs(fact: dict) -> list[SourceReference]:
    refs = fact.get("provenance", []) if isinstance(fact, dict) else []
    if not isinstance(refs, list):
        return []

    result: list[SourceReference] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        try:
            result.append(SourceReference.model_validate(ref))
        except Exception:
            continue
    return result


def _fact_texts(structured_analysis: dict, field: str) -> list[dict]:
    value = structured_analysis.get(field, []) if isinstance(structured_analysis, dict) else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _has_signal(facts: list[dict], pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(str(item.get("text", ""))) for item in facts)


def _issue(
    *,
    issue_id: str,
    issue_type: QualityIssueType,
    severity: QualitySeverity,
    affected_field: str,
    explanation: str,
    evidence: list[str],
    refs: list[SourceReference],
    question: str,
    kb_help: bool = False,
    human_mandatory: bool = True,
) -> QualityIssue:
    return QualityIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        severity=severity,
        affected_field=affected_field,
        explanation=explanation,
        evidence=evidence,
        source_references=refs,
        proposed_question=question,
        kb_retrieval_could_help=kb_help,
        human_confirmation_mandatory=human_mandatory,
    )


def run_deterministic_quality_checks(structured_analysis: dict) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    business_rules = _fact_texts(structured_analysis, "business_rules")
    expected_results = _fact_texts(structured_analysis, "expected_results")
    actors = _fact_texts(structured_analysis, "actors")
    permissions = _fact_texts(structured_analysis, "permissions")
    integrations = _fact_texts(structured_analysis, "integrations")
    transitions = _fact_texts(structured_analysis, "state_transitions")
    ambiguities = _fact_texts(structured_analysis, "ambiguities")
    contradictions = _fact_texts(structured_analysis, "contradictions")
    missing_info = _fact_texts(structured_analysis, "missing_information")
    assumptions = _fact_texts(structured_analysis, "assumptions")
    nfr = _fact_texts(structured_analysis, "non_functional_requirements")
    out_of_scope = _fact_texts(structured_analysis, "out_of_scope")

    if business_rules and not expected_results:
        refs = _to_refs(business_rules[0])
        issues.append(_issue(
            issue_id="QG-001",
            issue_type=QualityIssueType.EXPECTED_RESULT_DEFINITION,
            severity=QualitySeverity.BLOCKER,
            affected_field="expected_results",
            explanation="Business rules exist but expected results are missing.",
            evidence=[str(business_rules[0].get("text", ""))],
            refs=refs,
            question="What observable expected result should verify each listed business rule?",
            human_mandatory=True,
        ))

    for index, fact in enumerate(business_rules, start=1):
        text = str(fact.get("text", ""))
        refs = _to_refs(fact)

        if AMOUNT_RE.search(text) and not CURRENCY_RE.search(text):
            issues.append(_issue(
                issue_id=f"QG-002-{index}",
                issue_type=QualityIssueType.DATA_DEFINITION,
                severity=QualitySeverity.WARNING,
                affected_field="business_rules",
                explanation="Amount is present without currency definition.",
                evidence=[text],
                refs=refs,
                question="What currency applies to the stated amount(s)?",
                kb_help=False,
            ))

        if CALCULATION_RE.search(text) and not ROUNDING_RE.search(text):
            issues.append(_issue(
                issue_id=f"QG-003-{index}",
                issue_type=QualityIssueType.BOUNDARY_DEFINITION,
                severity=QualitySeverity.WARNING,
                affected_field="business_rules",
                explanation="Calculation rule does not define rounding or precision behavior.",
                evidence=[text],
                refs=refs,
                question="What rounding/precision rule should be applied to this calculation?",
            ))

        if DATE_DEPENDENT_RE.search(text):
            has_date_fact = _has_signal(_fact_texts(structured_analysis, "preconditions") + _fact_texts(structured_analysis, "triggers"), DATE_DEPENDENT_RE)
            if not has_date_fact:
                issues.append(_issue(
                    issue_id=f"QG-004-{index}",
                    issue_type=QualityIssueType.BOUNDARY_DEFINITION,
                    severity=QualitySeverity.WARNING,
                    affected_field="business_rules",
                    explanation="Date-dependent rule does not define an effective date boundary.",
                    evidence=[text],
                    refs=refs,
                    question="What effective date/time window applies to this rule?",
                ))

        if VAGUE_TERMS_RE.search(text):
            issues.append(_issue(
                issue_id=f"QG-005-{index}",
                issue_type=QualityIssueType.CLARITY,
                severity=QualitySeverity.WARNING,
                affected_field="business_rules",
                explanation="Vague wording detected without measurable definition.",
                evidence=[text],
                refs=refs,
                question="How should this behavior be defined with measurable acceptance criteria?",
            ))

    if actors and not permissions:
        refs = _to_refs(actors[0])
        issues.append(_issue(
            issue_id="QG-006",
            issue_type=QualityIssueType.PERMISSIONS,
            severity=QualitySeverity.WARNING,
            affected_field="permissions",
            explanation="Actors are defined but permissions are not specified.",
            evidence=[str(item.get("text", "")) for item in actors],
            refs=refs,
            question="What permissions are required for each actor?",
        ))

    for index, fact in enumerate(integrations, start=1):
        text = str(fact.get("text", ""))
        refs = _to_refs(fact)

        if INTEGRATION_RE.search(text) and not TIMEOUT_RE.search(text):
            issues.append(_issue(
                issue_id=f"QG-007-{index}",
                issue_type=QualityIssueType.INTEGRATION_BEHAVIOR,
                severity=QualitySeverity.WARNING,
                affected_field="integrations",
                explanation="Integration behavior does not include timeout/retry/failure handling.",
                evidence=[text],
                refs=refs,
                question="What timeout and failure behavior is expected for this integration?",
            ))

    for index, fact in enumerate(transitions, start=1):
        text = str(fact.get("text", ""))
        refs = _to_refs(fact)
        lowered = text.lower()
        has_from_to = ("from" in lowered and "to" in lowered) or "->" in lowered

        if not has_from_to:
            issues.append(_issue(
                issue_id=f"QG-008-{index}",
                issue_type=QualityIssueType.STATE_TRANSITIONS,
                severity=QualitySeverity.WARNING,
                affected_field="state_transitions",
                explanation="State transition does not clearly define initial and final states.",
                evidence=[text],
                refs=refs,
                question="What is the exact initial state and target state for this transition?",
            ))

    for index, fact in enumerate(expected_results, start=1):
        text = str(fact.get("text", ""))
        refs = _to_refs(fact)

        if not OBSERVABLE_RE.search(text):
            issues.append(_issue(
                issue_id=f"QG-009-{index}",
                issue_type=QualityIssueType.TESTABILITY,
                severity=QualitySeverity.WARNING,
                affected_field="expected_results",
                explanation="Expected result is not observable/verifiable.",
                evidence=[text],
                refs=refs,
                question="What observable outcome should be verified for this expected result?",
            ))

    # Promote explicit contradictions to blocker issues.
    for index, fact in enumerate(contradictions, start=1):
        text = str(fact.get("text", ""))
        issues.append(_issue(
            issue_id=f"QG-010-{index}",
            issue_type=QualityIssueType.CONTRADICTION,
            severity=QualitySeverity.BLOCKER,
            affected_field="contradictions",
            explanation="Contradiction exists in requirement sources.",
            evidence=[text],
            refs=_to_refs(fact),
            question="Which conflicting statement is authoritative and should be used for test design?",
            human_mandatory=True,
        ))

    for index, fact in enumerate(missing_info, start=1):
        text = str(fact.get("text", ""))
        issues.append(_issue(
            issue_id=f"QG-011-{index}",
            issue_type=QualityIssueType.MISSING_INFORMATION,
            severity=QualitySeverity.WARNING,
            affected_field="missing_information",
            explanation="Missing requirement information detected.",
            evidence=[text],
            refs=_to_refs(fact),
            question=f"Please clarify: {text}",
            human_mandatory=True,
        ))

    for index, fact in enumerate(assumptions, start=1):
        refs = _to_refs(fact)
        if not refs:
            text = str(fact.get("text", ""))
            issues.append(_issue(
                issue_id=f"QG-012-{index}",
                issue_type=QualityIssueType.UNSUPPORTED_ASSUMPTION,
                severity=QualitySeverity.WARNING,
                affected_field="assumptions",
                explanation="Assumption is not supported by source evidence.",
                evidence=[text],
                refs=[],
                question="Can this assumption be confirmed or replaced with explicit requirement text?",
                human_mandatory=True,
            ))

    if nfr and not any("performance" in str(item.get("text", "")).lower() or "latency" in str(item.get("text", "")).lower() for item in nfr):
        issues.append(_issue(
            issue_id="QG-013",
            issue_type=QualityIssueType.NON_FUNCTIONAL_EXPECTATIONS,
            severity=QualitySeverity.INFO,
            affected_field="non_functional_requirements",
            explanation="Non-functional requirements exist without clear measurable performance criteria.",
            evidence=[str(item.get("text", "")) for item in nfr],
            refs=_to_refs(nfr[0]),
            question="Are there measurable non-functional targets (latency, throughput, availability)?",
            human_mandatory=False,
        ))

    if not out_of_scope:
        issues.append(_issue(
            issue_id="QG-014",
            issue_type=QualityIssueType.SCOPE_CLARITY,
            severity=QualitySeverity.INFO,
            affected_field="out_of_scope",
            explanation="Out-of-scope boundaries are not explicitly defined.",
            evidence=["No out_of_scope facts provided."],
            refs=[],
            question="What is explicitly out of scope for this requirement?",
            human_mandatory=False,
        ))

    # Additional contradiction heuristic from mixed 'required' vs 'optional' semantics.
    grouped_by_key: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"required": set(), "optional": set()})
    candidate_fields = ["business_rules", "expected_results", "permissions"]
    for field in candidate_fields:
        for fact in _fact_texts(structured_analysis, field):
            text = str(fact.get("text", "")).strip()
            lowered = text.lower()
            if not text:
                continue
            tokens = [token for token in re.split(r"\W+", lowered) if token]
            key = " ".join(tokens[:4]) if tokens else lowered[:30]

            refs = _to_refs(fact)
            source_labels = {
                ref.source_identifier or ref.source_location or ref.source_classification
                for ref in refs
            } or {field}

            if "required" in lowered:
                grouped_by_key[key]["required"].update(source_labels)
            if "optional" in lowered:
                grouped_by_key[key]["optional"].update(source_labels)

    for key, value in grouped_by_key.items():
        if value["required"] and value["optional"]:
            evidence = [
                f"required seen in: {', '.join(sorted(value['required']))}",
                f"optional seen in: {', '.join(sorted(value['optional']))}",
            ]
            issues.append(_issue(
                issue_id=f"QG-015-{abs(hash(key)) % 10000}",
                issue_type=QualityIssueType.CONSISTENCY,
                severity=QualitySeverity.BLOCKER,
                affected_field="business_rules",
                explanation="Conflicting required vs optional semantics detected across sources.",
                evidence=evidence,
                refs=[],
                question="Should this behavior be required or optional? Please provide authoritative wording.",
                human_mandatory=True,
            ))

    # Deduplicate by normalized explanation+evidence+field.
    deduped: list[QualityIssue] = []
    seen = set()

    for issue in issues:
        fingerprint = (
            issue.issue_type.value,
            issue.severity.value,
            issue.affected_field.strip().lower(),
            issue.explanation.strip().lower(),
            "|".join(sorted(item.strip().lower() for item in issue.evidence if item.strip())),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(issue)

    return deduped
