from __future__ import annotations

import hashlib
import json
import re
import traceback
from pathlib import Path

from app.services.coverage_model.config import coverage_model_mode
from app.services.coverage_model.errors import (
    CoverageModelBuildError,
    CoverageModelError,
)
from app.services.coverage_model.models import (
    CoverageCombination,
    CoverageCondition,
    CoverageConditionType,
    CoverageDimension,
    CoverageDimensionValue,
    CoverageModelMode,
    CoverageModelV1,
    CoverageSourceReference,
    RiskPriority,
)
from app.utils.clarification_answers import (
    merge_clarifications_with_answers,
)
from knowledge.storage.utils import atomic_write_json, atomic_write_text

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")

_PROFILE_DIMENSION_HINTS = {
    "coverage type": ["coverage_type"],
    "insurance": ["insurance_type"],
    "treatment": ["treatment_code"],
    "effective": ["effective_date"],
    "role": ["role"],
    "state": ["state"],
    "api": ["integration_response"],
    "integration": ["integration_response"],
    "positive": ["path"],
    "negative": ["path"],
}


def _analysis_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "test-design"


def _knowledge_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "knowledge"


def _requirement_analysis_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "analysis"


def _read_json(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _write_json(path: Path, payload) -> str:
    atomic_write_json(path, payload)
    return str(path)


def _write_text(path: Path, content: str) -> str:
    atomic_write_text(path, content)
    return str(path)


def _normalize_id_part(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _stable_id(prefix: str, *parts: str) -> str:
    base = "|".join(_normalize_id_part(part) for part in parts if part is not None)
    digest = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _source_ref(source_type: str, excerpt: str, source_id: str = "") -> CoverageSourceReference:
    return CoverageSourceReference(
        source_type=source_type,
        source_identifier=source_id or None,
        source_excerpt=excerpt[:500],
    )


def _normalize_answers(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in [
            "answered_clarifications",
            "answers",
            "clarification_answers",
            "clarification_questions",
            "items",
        ]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _collect_jira_acceptance_criteria(summary: dict, analysis: dict) -> list[str]:
    criteria = []

    for item in summary.get("validations", []) if isinstance(summary, dict) else []:
        if isinstance(item, dict):
            text = str(item.get("description") or "").strip()
            if text:
                criteria.append(text)

    for item in analysis.get("requirement_items", []) if isinstance(analysis, dict) else []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if "acceptance" in item_type or "validation" in item_type:
            text = str(item.get("description") or "").strip()
            if text:
                criteria.append(text)

    return _dedupe_strings(criteria)


def _collect_jira_business_rules(summary: dict, structured_or_enriched: dict) -> list[str]:
    rules = []

    for item in summary.get("business_rules", []) if isinstance(summary, dict) else []:
        if isinstance(item, dict):
            text = str(item.get("description") or "").strip()
            if text:
                rules.append(text)

    if isinstance(structured_or_enriched, dict):
        # Structured analysis shape.
        raw_structured_rules = structured_or_enriched.get("business_rules", [])
        if isinstance(raw_structured_rules, list):
            for item in raw_structured_rules:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if text:
                        rules.append(text)

        # Enriched analysis shape.
        raw_jira_facts = structured_or_enriched.get("jira_derived_facts", [])
        if isinstance(raw_jira_facts, list):
            for item in raw_jira_facts:
                if not isinstance(item, dict):
                    continue
                fields = item.get("affected_requirement_fields", [])
                if isinstance(fields, list) and "business_rules" in fields:
                    text = str(item.get("statement") or "").strip()
                    if text:
                        rules.append(text)

    return _dedupe_strings(rules)


def _dedupe_strings(items: list[str]) -> list[str]:
    result = []
    seen = set()

    for item in items:
        clean = " ".join(str(item or "").split())
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)

    return result


def _build_dimensions(
    *,
    summary: dict,
    structured_or_enriched: dict,
    accepted_refs: list[dict],
    test_scope: dict,
) -> list[CoverageDimension]:
    dimensions: list[CoverageDimension] = []

    has_negative = bool(((test_scope or {}).get("scope_decision") or {}).get("negative"))
    has_positive = bool(((test_scope or {}).get("scope_decision") or {}).get("positive"))

    path_values = []
    if has_positive:
        path_values.append(
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "path", "positive"),
                value="positive",
                risk_priority=RiskPriority.MEDIUM,
                rationale="Positive flow is in test scope.",
            )
        )
    if has_negative:
        path_values.append(
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "path", "negative"),
                value="negative",
                risk_priority=RiskPriority.HIGH,
                rationale="Negative flow is in test scope.",
            )
        )

    if path_values:
        dimensions.append(
            CoverageDimension(
                dimension_id=_stable_id("CD", "path"),
                name="path",
                values=path_values,
                rationale="Represents positive/negative paths driven by scope.",
                source_refs=[_source_ref("test_scope", json.dumps((test_scope or {}).get("scope_decision", {}), ensure_ascii=False))],
            )
        )

    # Date/effective dimension only when date evidence exists.
    texts = []
    for section in [
        summary.get("business_rules", []),
        summary.get("functional_requirements", []),
        summary.get("validations", []),
    ] if isinstance(summary, dict) else []:
        if isinstance(section, list):
            for item in section:
                if isinstance(item, dict):
                    texts.append(str(item.get("description") or ""))

    has_date_signal = any(_DATE_RE.search(text or "") or "effective" in (text or "").lower() for text in texts)
    if has_date_signal:
        values = [
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "effective_date", "before"),
                value="before_effective_date",
                risk_priority=RiskPriority.HIGH,
                rationale="Boundary before effective date.",
            ),
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "effective_date", "on"),
                value="on_effective_date",
                risk_priority=RiskPriority.MEDIUM,
                rationale="Boundary at effective date.",
            ),
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "effective_date", "after"),
                value="after_effective_date",
                risk_priority=RiskPriority.MEDIUM,
                rationale="Boundary after effective date.",
            ),
        ]
        dimensions.append(
            CoverageDimension(
                dimension_id=_stable_id("CD", "effective_date"),
                name="effective_date",
                values=values,
                rationale="Date boundary coverage from requirement date signal.",
                source_refs=[_source_ref("jira", "Date/effective signal in requirement summary")],
            )
        )

    # Permission/role dimension when structured or enriched has permission-related fields.
    permission_signals = []
    if isinstance(structured_or_enriched, dict):
        for key in ["permissions", "actors", "qa_confirmed_facts", "knowledge_supported_facts"]:
            rows = structured_or_enriched.get(key, [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        text = str(row.get("text") or row.get("statement") or "")
                        if text:
                            permission_signals.append(text)

    if any("role" in item.lower() or "permission" in item.lower() or "authorize" in item.lower() for item in permission_signals):
        values = [
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "role", "allowed"),
                value="authorized_role",
                risk_priority=RiskPriority.HIGH,
                rationale="Authorized role path.",
            ),
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "role", "denied"),
                value="unauthorized_role",
                risk_priority=RiskPriority.HIGH,
                rationale="Permission-denied path.",
            ),
        ]
        dimensions.append(
            CoverageDimension(
                dimension_id=_stable_id("CD", "role"),
                name="role",
                values=values,
                rationale="Permission matrix dimension derived from role/permission signals.",
                source_refs=[_source_ref("jira", "Role/permission evidence in structured/enriched analysis")],
            )
        )

    # State dimension when transitions exist.
    state_values = []
    state_rows = structured_or_enriched.get("state_transitions", []) if isinstance(structured_or_enriched, dict) else []
    if isinstance(state_rows, list):
        for row in state_rows:
            if isinstance(row, dict):
                text = str(row.get("text") or "").strip()
                if text:
                    state_values.append(text)

    if state_values:
        values = [
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "state", value),
                value=value,
                risk_priority=RiskPriority.MEDIUM,
                rationale="State transition extracted from Jira structured analysis.",
            )
            for value in _dedupe_strings(state_values)
        ]

        dimensions.append(
            CoverageDimension(
                dimension_id=_stable_id("CD", "state"),
                name="state",
                values=values,
                rationale="State-transition coverage dimension.",
                source_refs=[_source_ref("jira", "State transitions")],
            )
        )

    # Integration response dimension when integration is in scope or referenced.
    integration_signals = []
    for section in [summary.get("integrations", [])] if isinstance(summary, dict) else []:
        if isinstance(section, list):
            for item in section:
                if isinstance(item, dict):
                    text = str(item.get("description") or "").strip()
                    if text:
                        integration_signals.append(text)

    scope_integration = bool(((test_scope or {}).get("scope_decision") or {}).get("integration"))

    if scope_integration or integration_signals:
        values = [
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "integration_response", "success"),
                value="success",
                risk_priority=RiskPriority.MEDIUM,
                rationale="Integration success response.",
            ),
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "integration_response", "failure"),
                value="failure",
                risk_priority=RiskPriority.HIGH,
                rationale="Integration failure response.",
            ),
            CoverageDimensionValue(
                value_id=_stable_id("CDV", "integration_response", "timeout"),
                value="timeout",
                risk_priority=RiskPriority.HIGH,
                rationale="Integration timeout response.",
            ),
        ]
        dimensions.append(
            CoverageDimension(
                dimension_id=_stable_id("CD", "integration_response"),
                name="integration_response",
                values=values,
                rationale="Integration behavior coverage.",
                source_refs=[_source_ref("jira", "Integration references in summary/scope")],
            )
        )

    # Domain profile suggestions (not mandatory) from accepted references.
    accepted_blob = "\n".join(str(item.get("excerpt") or "") for item in accepted_refs if isinstance(item, dict)).lower()
    for keyword, suggested_dimensions in _PROFILE_DIMENSION_HINTS.items():
        if keyword not in accepted_blob:
            continue
        for name in suggested_dimensions:
            existing = next((item for item in dimensions if item.name == name), None)
            if existing:
                continue
            values = [
                CoverageDimensionValue(
                    value_id=_stable_id("CDV", name, "profile-suggested"),
                    value="profile_suggested",
                    risk_priority=RiskPriority.MEDIUM,
                    rationale="Suggested by domain profile evidence.",
                )
            ]
            dimensions.append(
                CoverageDimension(
                    dimension_id=_stable_id("CD", name),
                    name=name,
                    values=values,
                    suggested_by_profile=True,
                    rationale=f"Dimension suggested by accepted reference keyword: {keyword}",
                    source_refs=[_source_ref("knowledge_base", keyword)],
                )
            )

    return dimensions


def _find_dimension(dimensions: list[CoverageDimension], name: str) -> CoverageDimension | None:
    for item in dimensions:
        if item.name == name:
            return item
    return None


def _condition_id(condition_type: CoverageConditionType, title: str, refs: list[CoverageSourceReference]) -> str:
    ref_key = "|".join((ref.source_identifier or "") + ":" + (ref.citation or "") for ref in refs)
    return _stable_id("CC", condition_type.value, title, ref_key)


def _build_conditions(
    *,
    acceptance_criteria: list[str],
    business_rules: list[str],
    clarifications: list[dict],
    structured_or_enriched: dict,
    accepted_refs: list[dict],
    historical_defects: list[dict],
    existing_test_hints: list[dict],
    dimensions: list[CoverageDimension],
    out_of_scope_reasons: list[dict],
) -> tuple[list[CoverageCondition], list[CoverageCombination], list[CoverageCombination], list[str]]:
    conditions: list[CoverageCondition] = []
    excluded: list[CoverageCombination] = []
    out_of_scope: list[CoverageCombination] = []
    uncovered_questions: list[str] = []

    # Mandatory conditions from acceptance criteria and business rules.
    for text in acceptance_criteria + business_rules:
        refs = [_source_ref("jira", text)]
        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.MANDATORY, text, refs),
                condition_type=CoverageConditionType.MANDATORY,
                title=text,
                mandatory=True,
                risk_priority=RiskPriority.HIGH,
                rationale="Mapped directly from Jira acceptance criteria/business rule.",
                source_refs=refs,
            )
        )

    # Approved clarifications as mandatory if final answer exists.
    for item in clarifications:
        answer = str(item.get("final_answer") or item.get("answer") or "").strip()
        question = str(item.get("question") or "").strip()
        if not answer:
            if question:
                uncovered_questions.append(question)
            continue

        title = f"Clarification-confirmed: {answer}"
        refs = [_source_ref("clarification", f"Q: {question} A: {answer}", str(item.get("question_id") or ""))]
        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.MANDATORY, title, refs),
                condition_type=CoverageConditionType.MANDATORY,
                title=title,
                mandatory=True,
                risk_priority=RiskPriority.HIGH,
                rationale="Approved clarification answer.",
                source_refs=refs,
            )
        )

    # Boundary conditions from date or numeric evidence.
    date_dimension = _find_dimension(dimensions, "effective_date")
    if date_dimension:
        for value in date_dimension.values:
            title = f"Date boundary: {value.value}"
            refs = date_dimension.source_refs
            conditions.append(
                CoverageCondition(
                    condition_id=_condition_id(CoverageConditionType.BOUNDARY, title, refs),
                    condition_type=CoverageConditionType.BOUNDARY,
                    title=title,
                    dimension_value_refs={date_dimension.dimension_id: value.value_id},
                    mandatory=False,
                    risk_priority=RiskPriority.HIGH if "before" in value.value else RiskPriority.MEDIUM,
                    rationale="Meaningful date boundary selected without Cartesian expansion.",
                    source_refs=refs,
                )
            )

    # Numeric boundaries from business rules.
    for text in business_rules:
        nums = _NUMBER_RE.findall(text)
        if not nums:
            continue
        number = nums[0]
        for boundary_type in ["below", "at", "above"]:
            title = f"Numeric boundary {boundary_type} {number}"
            refs = [_source_ref("jira", text)]
            conditions.append(
                CoverageCondition(
                    condition_id=_condition_id(CoverageConditionType.BOUNDARY, title, refs),
                    condition_type=CoverageConditionType.BOUNDARY,
                    title=title,
                    mandatory=False,
                    risk_priority=RiskPriority.MEDIUM,
                    rationale="Representative boundary condition from numeric rule.",
                    source_refs=refs,
                )
            )

    # Negative and permission conditions.
    path_dimension = _find_dimension(dimensions, "path")
    if path_dimension:
        negative_value = next((item for item in path_dimension.values if item.value == "negative"), None)
        if negative_value:
            refs = path_dimension.source_refs
            conditions.append(
                CoverageCondition(
                    condition_id=_condition_id(CoverageConditionType.NEGATIVE, "Representative negative flow", refs),
                    condition_type=CoverageConditionType.NEGATIVE,
                    title="Representative negative flow",
                    dimension_value_refs={path_dimension.dimension_id: negative_value.value_id},
                    mandatory=False,
                    risk_priority=RiskPriority.HIGH,
                    rationale="Negative path included as representative case.",
                    source_refs=refs,
                )
            )

    role_dimension = _find_dimension(dimensions, "role")
    if role_dimension and len(role_dimension.values) >= 2:
        allowed = role_dimension.values[0]
        denied = role_dimension.values[1]
        refs = role_dimension.source_refs

        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.PERMISSION, "Authorized role access", refs),
                condition_type=CoverageConditionType.PERMISSION,
                title="Authorized role access",
                dimension_value_refs={role_dimension.dimension_id: allowed.value_id},
                risk_priority=RiskPriority.HIGH,
                rationale="Permission matrix include authorized path.",
                source_refs=refs,
            )
        )

        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.PERMISSION, "Unauthorized role denied", refs),
                condition_type=CoverageConditionType.PERMISSION,
                title="Unauthorized role denied",
                dimension_value_refs={role_dimension.dimension_id: denied.value_id},
                risk_priority=RiskPriority.HIGH,
                rationale="Permission matrix include denied path.",
                source_refs=refs,
            )
        )

        # Impossible combination example.
        if path_dimension:
            positive = next((item for item in path_dimension.values if item.value == "positive"), None)
            if positive:
                bindings = {
                    role_dimension.dimension_id: denied.value_id,
                    path_dimension.dimension_id: positive.value_id,
                }
                excluded.append(
                    CoverageCombination(
                        combination_id=_stable_id("CX", "impossible", *[f"{k}:{v}" for k, v in sorted(bindings.items())]),
                        dimension_value_refs=bindings,
                        reason="impossible_combination",
                        rationale="Unauthorized role cannot produce a successful positive path.",
                        source_refs=refs,
                    )
                )

    # State transition conditions.
    state_dimension = _find_dimension(dimensions, "state")
    if state_dimension:
        for value in state_dimension.values:
            refs = state_dimension.source_refs
            title = f"State transition: {value.value}"
            conditions.append(
                CoverageCondition(
                    condition_id=_condition_id(CoverageConditionType.STATE_TRANSITION, title, refs),
                    condition_type=CoverageConditionType.STATE_TRANSITION,
                    title=title,
                    dimension_value_refs={state_dimension.dimension_id: value.value_id},
                    risk_priority=RiskPriority.MEDIUM,
                    rationale="State transition condition from structured analysis.",
                    source_refs=refs,
                )
            )

    # Integration conditions (success/failure/timeout) when relevant.
    integration_dimension = _find_dimension(dimensions, "integration_response")
    if integration_dimension:
        for value in integration_dimension.values:
            refs = integration_dimension.source_refs
            priority = RiskPriority.HIGH if value.value in {"failure", "timeout"} else RiskPriority.MEDIUM
            title = f"Integration response: {value.value}"
            conditions.append(
                CoverageCondition(
                    condition_id=_condition_id(CoverageConditionType.INTEGRATION, title, refs),
                    condition_type=CoverageConditionType.INTEGRATION,
                    title=title,
                    dimension_value_refs={integration_dimension.dimension_id: value.value_id},
                    risk_priority=priority,
                    rationale="Integration behavior included without full Cartesian product.",
                    source_refs=refs,
                )
            )

    # Accepted official references can suggest missing context (KB source-separated).
    for item in accepted_refs:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "UNKNOWN").upper()
        excerpt = str(item.get("excerpt") or "").strip()
        citation = str(item.get("citation") or "").strip()
        if not excerpt:
            continue

        if source_type in {"DEFECT", "HISTORICAL_DEFECT"}:
            continue

        refs = [CoverageSourceReference(
            source_type="knowledge_base",
            source_identifier=str(item.get("source_result_id") or "") or None,
            source_location=str(item.get("collection_id") or "") or None,
            citation=citation or None,
            source_excerpt=excerpt,
        )]

        title = f"KB-supported context: {excerpt[:120]}"
        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.MANDATORY, title, refs),
                condition_type=CoverageConditionType.MANDATORY,
                title=title,
                mandatory=False,
                risk_priority=RiskPriority.MEDIUM,
                rationale="Accepted official reference suggests additional business-rule context.",
                source_refs=refs,
            )
        )

    # Historical defects only influence regression-risk coverage.
    for item in historical_defects:
        excerpt = str(item.get("excerpt") or "").strip()
        if not excerpt:
            continue
        refs = [CoverageSourceReference(
            source_type="historical_defect",
            source_identifier=str(item.get("source_result_id") or "") or None,
            source_location=str(item.get("collection_id") or "") or None,
            citation=str(item.get("citation") or "") or None,
            source_excerpt=excerpt,
        )]

        title = f"Regression risk from historical defect: {excerpt[:100]}"
        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.REGRESSION_RISK, title, refs),
                condition_type=CoverageConditionType.REGRESSION_RISK,
                title=title,
                risk_priority=RiskPriority.HIGH,
                rationale="Historical defects are used only as regression risk coverage.",
                source_refs=refs,
            )
        )

    # Existing tests as coverage hints (non-authoritative).
    for item in existing_test_hints:
        hint = str(item.get("excerpt") or "").strip()
        if not hint:
            continue
        refs = [CoverageSourceReference(
            source_type="existing_test",
            source_identifier=str(item.get("source_result_id") or "") or None,
            source_location=str(item.get("collection_id") or "") or None,
            citation=str(item.get("citation") or "") or None,
            source_excerpt=hint,
        )]
        conditions.append(
            CoverageCondition(
                condition_id=_condition_id(CoverageConditionType.MANDATORY, f"Coverage hint: {hint[:80]}", refs),
                condition_type=CoverageConditionType.MANDATORY,
                title=f"Coverage hint: {hint[:80]}",
                risk_priority=RiskPriority.LOW,
                rationale="Existing tests provide coverage hints only and are not authoritative requirements.",
                source_refs=refs,
            )
        )

    # Out-of-scope combinations from scope exclusions.
    for row in out_of_scope_reasons:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not category:
            continue
        bindings = {"excluded_category": category}
        refs = [_source_ref("test_scope", f"{category}: {reason}")]
        out_of_scope.append(
            CoverageCombination(
                combination_id=_stable_id("CO", "out_of_scope", category, reason),
                dimension_value_refs=bindings,
                reason="out_of_scope",
                rationale=reason or "Category excluded by scope decision.",
                source_refs=refs,
            )
        )

    # Remove duplicate conditions by ID.
    deduped_conditions: list[CoverageCondition] = []
    seen_condition_ids = set()
    for item in conditions:
        if item.condition_id in seen_condition_ids:
            continue
        seen_condition_ids.add(item.condition_id)
        deduped_conditions.append(item)

    return deduped_conditions, excluded, out_of_scope, _dedupe_strings(uncovered_questions)


def _risk_summary(conditions: list[CoverageCondition]) -> dict:
    counts = {RiskPriority.HIGH.value: 0, RiskPriority.MEDIUM.value: 0, RiskPriority.LOW.value: 0}
    for item in conditions:
        counts[item.risk_priority.value] += 1

    return {
        "total_conditions": len(conditions),
        "high_risk_conditions": counts[RiskPriority.HIGH.value],
        "medium_risk_conditions": counts[RiskPriority.MEDIUM.value],
        "low_risk_conditions": counts[RiskPriority.LOW.value],
    }


def _coverage_model_id(
    *,
    ticket_id: str,
    requirement_refs: list[str],
    dimensions: list[CoverageDimension],
    conditions: list[CoverageCondition],
    excluded_combinations: list[CoverageCombination],
    out_of_scope_combinations: list[CoverageCombination],
    uncovered_questions: list[str],
) -> str:
    material_signature = {
        "requirement_refs": sorted(requirement_refs),
        "dimensions": sorted(
            (
                item.dimension_id,
                tuple(sorted(value.value_id for value in item.values)),
            )
            for item in dimensions
        ),
        "condition_ids": sorted(item.condition_id for item in conditions),
        "excluded_ids": sorted(item.combination_id for item in excluded_combinations),
        "out_of_scope_ids": sorted(
            item.combination_id for item in out_of_scope_combinations
        ),
        "uncovered_questions": sorted(
            _normalize_id_part(item) for item in uncovered_questions
        ),
    }
    return _stable_id(
        "CM",
        ticket_id,
        json.dumps(material_signature, sort_keys=True, ensure_ascii=False),
    )


def _evaluate_model(
    *,
    acceptance_criteria: list[str],
    conditions: list[CoverageCondition],
    excluded_combinations: list[CoverageCombination],
    out_of_scope_combinations: list[CoverageCombination],
) -> dict:
    condition_titles = "\n".join(item.title.lower() for item in conditions)

    mapped = 0
    for item in acceptance_criteria:
        text = item.lower().strip()
        if text and (text in condition_titles or any(token in condition_titles for token in text.split()[:3])):
            mapped += 1

    acceptance_mapping = mapped / len(acceptance_criteria) if acceptance_criteria else 1.0

    critical_types = {
        CoverageConditionType.MANDATORY,
        CoverageConditionType.BOUNDARY,
        CoverageConditionType.NEGATIVE,
        CoverageConditionType.INTEGRATION,
    }
    critical_total = len([item for item in conditions if item.condition_type in critical_types])
    critical_high = len([item for item in conditions if item.condition_type in critical_types and item.risk_priority == RiskPriority.HIGH])
    critical_condition_coverage = critical_high / critical_total if critical_total else 1.0

    boundary_needed = any("date" in item.lower() or _NUMBER_RE.search(item) for item in acceptance_criteria)
    boundary_present = any(item.condition_type == CoverageConditionType.BOUNDARY for item in conditions)
    missing_boundary_rate = 1.0 if boundary_needed and not boundary_present else 0.0

    meaningless_count = len([item for item in conditions if not item.source_refs or not any((ref.source_identifier or ref.citation or ref.source_excerpt) for ref in item.source_refs)])
    meaningless_combination_rate = meaningless_count / len(conditions) if conditions else 0.0

    out_of_scope_inclusion_rate = 0.0
    if out_of_scope_combinations:
        out_scope_labels = {str(item.dimension_value_refs.get("excluded_category", "")).lower() for item in out_of_scope_combinations}
        included_labels = [item for item in conditions if any(label and label in item.title.lower() for label in out_scope_labels)]
        out_of_scope_inclusion_rate = len(included_labels) / len(conditions) if conditions else 0.0

    regression_inclusion = 1.0 if any(item.condition_type == CoverageConditionType.REGRESSION_RISK for item in conditions) else 0.0

    source_complete = len([
        item
        for item in conditions
        if item.source_refs and any((ref.source_type and (ref.source_identifier or ref.citation or ref.source_excerpt)) for ref in item.source_refs)
    ])
    source_reference_completeness = source_complete / len(conditions) if conditions else 0.0

    return {
        "acceptance_criteria_mapping": round(acceptance_mapping, 4),
        "critical_condition_coverage": round(critical_condition_coverage, 4),
        "missing_boundary_rate": round(missing_boundary_rate, 4),
        "meaningless_combination_rate": round(meaningless_combination_rate, 4),
        "out_of_scope_inclusion_rate": round(out_of_scope_inclusion_rate, 4),
        "regression_risk_inclusion": round(regression_inclusion, 4),
        "source_reference_completeness": round(source_reference_completeness, 4),
    }


def _build_analysis_markdown(
    *,
    ticket_id: str,
    mode: CoverageModelMode,
    model: CoverageModelV1,
    existing_scenarios: list,
) -> str:
    scenario_count = len([item for item in existing_scenarios if isinstance(item, dict)])
    condition_count = len(model.coverage_conditions)
    ratio = condition_count / scenario_count if scenario_count else 0.0

    lines = [
        f"# Coverage Analysis: {ticket_id}",
        "",
        f"- Mode: {mode.value}",
        f"- Coverage model ID: {model.coverage_model_id}",
        f"- Coverage conditions: {condition_count}",
        f"- Existing scenarios found: {scenario_count}",
        f"- Condition-to-scenario ratio: {ratio:.2f}",
        "",
        "## Selected Dimensions",
        "",
    ]

    if model.dimensions:
        for dimension in model.dimensions:
            values = ", ".join(value.value for value in dimension.values) or "none"
            lines.append(
                f"- `{dimension.dimension_id}` **{dimension.name}**: {values} — "
                f"{dimension.rationale}"
            )
    else:
        lines.append("- None selected from the available ticket evidence.")

    sections = [
        ("Mandatory Coverage", {CoverageConditionType.MANDATORY}),
        ("Boundary Conditions", {CoverageConditionType.BOUNDARY}),
        ("Negative Paths", {CoverageConditionType.NEGATIVE}),
        ("Integration Failures", {CoverageConditionType.INTEGRATION}),
        ("Permission Conditions", {CoverageConditionType.PERMISSION}),
        ("State Transitions", {CoverageConditionType.STATE_TRANSITION}),
        ("Regression Risks", {CoverageConditionType.REGRESSION_RISK}),
    ]

    for title, condition_types in sections:
        lines.extend(["", f"## {title}", ""])
        matching = [
            item
            for item in model.coverage_conditions
            if item.condition_type in condition_types
        ]
        if title == "Integration Failures":
            matching = [
                item
                for item in matching
                if any(token in item.title.casefold() for token in ("failure", "timeout"))
            ]

        if not matching:
            lines.append("- None identified.")
            continue

        for item in matching:
            lines.append(
                f"- `{item.condition_id}` [{item.risk_priority.value}] "
                f"{item.title} — {item.rationale}"
            )

    lines.extend(["", "## Excluded Combinations", ""])
    exclusions = [*model.excluded_combinations, *model.out_of_scope_combinations]
    if exclusions:
        for item in exclusions:
            lines.append(
                f"- `{item.combination_id}` ({item.reason}): "
                f"{item.rationale or item.dimension_value_refs}"
            )
    else:
        lines.append("- None identified.")

    lines.extend(["", "## Unresolved Questions", ""])
    if model.uncovered_questions:
        lines.extend(f"- {question}" for question in model.uncovered_questions)
    else:
        lines.append("- None identified.")

    lines.extend(["", "## Source Traceability", ""])
    if model.source_refs:
        for ref in model.source_refs:
            identifier = ref.source_identifier or ref.citation or "inline evidence"
            lines.append(f"- **{ref.source_type}**: {identifier}")
    else:
        lines.append("- No source references were available.")

    lines.extend(["", "## Metrics", ""])

    for key, value in model.evaluation_metrics.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## Selection Strategy",
            "",
            "- No full Cartesian product was generated.",
            "- Conditions were selected from mandatory, boundary, negative, integration, permission, transition, and regression obligations.",
            "- Impossible and out-of-scope combinations were explicitly excluded with rationale.",
        ]
    )

    if mode == CoverageModelMode.SHADOW:
        lines.extend(
            [
                "",
                "## Shadow Note",
                "",
                "Coverage model is generated for analysis only and does not alter scenario generation input in shadow mode.",
            ]
        )

    return "\n".join(lines)


def _run_active_coverage_model_builder(
    state: dict,
    mode: CoverageModelMode,
) -> dict:
    ticket_id = str(state.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("ticket_id is required")

    summary = state.get("requirement_summary") or _read_json(_requirement_analysis_dir(ticket_id) / "requirement_summary.json", {})
    analysis = state.get("analysis") or _read_json(_requirement_analysis_dir(ticket_id) / "requirement_analysis.json", {})
    test_scope = state.get("test_scope") or _read_json(_requirement_analysis_dir(ticket_id) / "test_scope.json", {})
    structured_analysis = state.get("structured_analysis") or _read_json(_requirement_analysis_dir(ticket_id) / "structured_analysis.json", {})
    active_enriched = state.get("active_enriched_analysis")
    if not active_enriched:
        enrichment_approval = (
            state.get("enrichment_approval")
            or _read_json(
                _requirement_analysis_dir(ticket_id) / "enrichment_approval.json",
                {},
            )
        )
        if isinstance(enrichment_approval, dict) and enrichment_approval.get("approved") is True:
            active_enriched = _read_json(
                _requirement_analysis_dir(ticket_id) / "enriched_analysis.json",
                {},
            )

    structured_or_enriched = active_enriched if isinstance(active_enriched, dict) and active_enriched else structured_analysis

    selected_refs = [
        item
        for item in _read_json(_knowledge_dir(ticket_id) / "selected_references.json", [])
        if isinstance(item, dict)
        and str(item.get("classification") or "").upper() == "ACCEPTED"
    ]

    review_records = [
        item
        for item in _read_json(_knowledge_dir(ticket_id) / "review_records.json", [])
        if isinstance(item, dict)
    ]

    clarification_answers = (
        state.get("clarification_answers")
        or _read_json(
            _requirement_analysis_dir(ticket_id) / "clarification_answers.json",
            {},
        )
    )
    clarification_questions = (
        state.get("clarifications")
        or _read_json(
            _requirement_analysis_dir(ticket_id) / "clarifications.json",
            [],
        )
    )
    normalized_questions = _normalize_answers(clarification_questions)
    clarifications = (
        merge_clarifications_with_answers(
            normalized_questions,
            clarification_answers,
        )
        if normalized_questions
        else _normalize_answers(clarification_answers)
    )

    historical_defects = [
        item
        for item in [*review_records, *selected_refs]
        if str(item.get("source_type") or "").upper()
        in {"DEFECT", "HISTORICAL_DEFECT"}
        and str(item.get("classification") or "").upper()
        in {"ACCEPTED", "HISTORICAL_CONTEXT_ONLY"}
    ]

    existing_test_hints = [
        item for item in selected_refs
        if str(item.get("source_type") or "").upper() in {"TEST_CASE", "EXISTING_TEST_CASE"}
    ]

    acceptance_criteria = _collect_jira_acceptance_criteria(summary, analysis)
    business_rules = _collect_jira_business_rules(summary, structured_or_enriched)

    requirement_refs = []
    for item in analysis.get("requirement_items", []) if isinstance(analysis, dict) else []:
        if isinstance(item, dict):
            rid = str(item.get("requirement_id") or "").strip()
            if rid:
                requirement_refs.append(rid)
    for section_name in (
        "functional_requirements",
        "business_rules",
        "validations",
        "integrations",
        "error_handling",
        "non_functional_requirements",
    ):
        rows = summary.get(section_name, []) if isinstance(summary, dict) else []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                rid = str(item.get("id") or item.get("requirement_id") or "").strip()
                if rid:
                    requirement_refs.append(rid)
    requirement_refs = _dedupe_strings(requirement_refs)

    dimensions = _build_dimensions(
        summary=summary if isinstance(summary, dict) else {},
        structured_or_enriched=structured_or_enriched if isinstance(structured_or_enriched, dict) else {},
        accepted_refs=selected_refs,
        test_scope=test_scope if isinstance(test_scope, dict) else {},
    )

    out_of_scope_reasons = ((test_scope or {}).get("excluded_categories") or []) if isinstance(test_scope, dict) else []

    coverage_conditions, excluded, out_of_scope, uncovered_questions = _build_conditions(
        acceptance_criteria=acceptance_criteria,
        business_rules=business_rules,
        clarifications=clarifications,
        structured_or_enriched=structured_or_enriched if isinstance(structured_or_enriched, dict) else {},
        accepted_refs=selected_refs,
        historical_defects=historical_defects,
        existing_test_hints=existing_test_hints,
        dimensions=dimensions,
        out_of_scope_reasons=out_of_scope_reasons if isinstance(out_of_scope_reasons, list) else [],
    )

    source_refs = []
    for row in coverage_conditions:
        source_refs.extend(row.source_refs)

    # Deduplicate source refs.
    deduped_source_refs = []
    seen_ref = set()
    for ref in source_refs:
        key = (
            ref.source_type,
            ref.source_identifier or "",
            ref.citation or "",
            ref.source_excerpt or "",
        )
        if key in seen_ref:
            continue
        seen_ref.add(key)
        deduped_source_refs.append(ref)

    model = CoverageModelV1(
        coverage_model_id=_coverage_model_id(
            ticket_id=ticket_id,
            requirement_refs=requirement_refs,
            dimensions=dimensions,
            conditions=coverage_conditions,
            excluded_combinations=excluded,
            out_of_scope_combinations=out_of_scope,
            uncovered_questions=uncovered_questions,
        ),
        ticket_id=ticket_id,
        requirement_refs=requirement_refs,
        dimensions=dimensions,
        coverage_conditions=coverage_conditions,
        excluded_combinations=excluded,
        out_of_scope_combinations=out_of_scope,
        risk_summary=_risk_summary(coverage_conditions),
        uncovered_questions=uncovered_questions,
        source_refs=deduped_source_refs,
        generation_metadata={
            "builder": "deterministic_coverage_model_builder",
            "builder_version": "phase7-v1",
            "mode": mode.value,
            "accepted_knowledge_reference_count": len(selected_refs),
            "historical_defect_count": len(historical_defects),
            "existing_test_hint_count": len(existing_test_hints),
            "full_cartesian_product_generated": False,
        },
    )

    model.evaluation_metrics = _evaluate_model(
        acceptance_criteria=acceptance_criteria,
        conditions=coverage_conditions,
        excluded_combinations=excluded,
        out_of_scope_combinations=out_of_scope,
    )

    existing_scenarios = state.get("scenarios")
    if not isinstance(existing_scenarios, list):
        existing_scenarios = _read_json(_requirement_analysis_dir(ticket_id) / "scenarios.json", [])
        if not isinstance(existing_scenarios, list):
            existing_scenarios = []

    test_design_dir = _analysis_dir(ticket_id)
    model_payload = model.model_dump(mode="json")
    _write_json(test_design_dir / "coverage_model.json", model_payload)

    analysis_md = _build_analysis_markdown(
        ticket_id=ticket_id,
        mode=mode,
        model=model,
        existing_scenarios=existing_scenarios,
    )
    _write_text(test_design_dir / "coverage_analysis.md", analysis_md)

    active_for_scenarios = mode == CoverageModelMode.ENABLED

    return {
        "coverage_model_run": {
            "enabled": True,
            "mode": mode.value,
            "status": "succeeded",
            "active_for_scenarios": active_for_scenarios,
        },
        "coverage_model": model_payload,
        "coverage_analysis": analysis_md,
        "active_coverage_model": model_payload if active_for_scenarios else None,
    }


def _coverage_failure_payload(
    *,
    ticket_id: str,
    mode: CoverageModelMode,
    error: Exception,
) -> dict:
    return {
        "ticket_id": ticket_id,
        "mode": mode.value,
        "status": "failed",
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ),
    }


def run_coverage_model_builder(state: dict) -> dict:
    mode = coverage_model_mode()

    if mode == CoverageModelMode.OFF:
        return {
            "coverage_model_run": {
                "enabled": False,
                "mode": mode.value,
                "status": "skipped",
                "active_for_scenarios": False,
            },
            "active_coverage_model": None,
        }

    ticket_id = str(state.get("ticket_id") or "").strip()

    try:
        return _run_active_coverage_model_builder(state, mode)
    except Exception as error:
        failure = _coverage_failure_payload(
            ticket_id=ticket_id,
            mode=mode,
            error=error,
        )

        if ticket_id:
            _write_json(_analysis_dir(ticket_id) / "coverage_model_error.json", failure)

        if mode == CoverageModelMode.SHADOW:
            return {
                "coverage_model_run": {
                    "enabled": True,
                    "mode": mode.value,
                    "status": "failed",
                    "active_for_scenarios": False,
                },
                "coverage_model_error": failure,
                "active_coverage_model": None,
            }

        if isinstance(error, CoverageModelError):
            raise

        raise CoverageModelBuildError(
            f"Coverage model generation failed for ticket {ticket_id or '<missing>'}: "
            f"{error}"
        ) from error


def build_scenario_coverage_context(model_payload: dict) -> dict:
    """Return the concise enabled-mode adapter consumed by scenario prompts."""
    model = CoverageModelV1.model_validate(model_payload)
    grouped: dict[str, list[dict]] = {
        "mandatory_conditions": [],
        "boundary_conditions": [],
        "negative_conditions": [],
        "integration_conditions": [],
        "permission_conditions": [],
        "state_transition_conditions": [],
        "regression_risks": [],
    }
    group_by_type = {
        CoverageConditionType.MANDATORY: "mandatory_conditions",
        CoverageConditionType.BOUNDARY: "boundary_conditions",
        CoverageConditionType.NEGATIVE: "negative_conditions",
        CoverageConditionType.INTEGRATION: "integration_conditions",
        CoverageConditionType.PERMISSION: "permission_conditions",
        CoverageConditionType.STATE_TRANSITION: "state_transition_conditions",
        CoverageConditionType.REGRESSION_RISK: "regression_risks",
    }

    for condition in model.coverage_conditions:
        source_refs = []
        for ref in condition.source_refs:
            source_refs.append(
                {
                    "source_type": ref.source_type,
                    "source_identifier": ref.source_identifier,
                    "citation": ref.citation,
                }
            )

        grouped[group_by_type[condition.condition_type]].append(
            {
                "coverage_id": condition.condition_id,
                "title": condition.title,
                "risk_priority": condition.risk_priority.value,
                "rationale": condition.rationale,
                "source_refs": source_refs,
            }
        )

    return {
        "coverage_model_id": model.coverage_model_id,
        "requirement_refs": model.requirement_refs,
        **grouped,
        "excluded_combinations": [
            {
                "coverage_id": item.combination_id,
                "reason": item.reason,
                "rationale": item.rationale,
            }
            for item in model.excluded_combinations
        ],
        "out_of_scope_combinations": [
            {
                "coverage_id": item.combination_id,
                "reason": item.reason,
                "rationale": item.rationale,
            }
            for item in model.out_of_scope_combinations
        ],
        "uncovered_questions": model.uncovered_questions,
    }
