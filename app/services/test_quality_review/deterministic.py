from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

from app.services.test_case_generator_v2.inputs import source_catalog
from app.services.test_case_generator_v2.models import GeneratorSourceReference
from app.services.test_quality_review.models import (
    DuplicateGroup,
    MissingCoverageItem,
    ReviewCategory,
    ReviewSeverity,
    TestQualityIssue,
)


_UNSUPPORTED_NUMBER_RE = re.compile(
    r"(?:[$€£]\s*\d+(?:[.,]\d+)?|\b\d{2,}(?:[.,]\d+)?\s*%?)"
)
_QUOTED_MESSAGE_RE = re.compile(r"[\"']([^\"']{3,})[\"']")
_VAGUE_PHRASES = {"works correctly", "as expected", "appropriate", "valid result"}


def _clean(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _stable_id(category: str, case_id: str | None, explanation: str) -> str:
    raw = f"{category}|{case_id or ''}|{_clean(explanation)}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"TQI-{digest}"


def _source_refs(items) -> list[GeneratorSourceReference]:
    refs = []
    for item in items or []:
        try:
            refs.append(GeneratorSourceReference.model_validate(item))
        except Exception:
            continue
    return refs


def _issue(
    category: ReviewCategory,
    explanation: str,
    correction: str,
    *,
    case_id: str | None = None,
    severity: ReviewSeverity = ReviewSeverity.BLOCKER,
    source_refs=None,
    auto_correctable: bool = False,
    detected_by: str = "deterministic",
) -> TestQualityIssue:
    return TestQualityIssue(
        issue_id=_stable_id(category.value, case_id, explanation),
        severity=severity,
        category=category,
        test_case_id=case_id,
        source_refs=_source_refs(source_refs),
        explanation=explanation,
        recommended_correction=correction,
        auto_correctable=auto_correctable,
        blocks_export=severity == ReviewSeverity.BLOCKER,
        detected_by=detected_by,
    )


def _case_rows(payload) -> list[dict]:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if isinstance(payload, dict):
        payload = payload.get("test_cases") or payload.get("testcases") or []
    return [item for item in payload or [] if isinstance(item, dict)]


def _evidence_corpus(inputs: dict) -> str:
    values = [inputs.get("authoritative_jira_source", "")]
    values.extend(
        json.dumps(inputs.get(key, {}), ensure_ascii=False)
        for key in (
            "approved_analysis",
            "accepted_knowledge_references",
            "confirmed_clarifications",
        )
    )
    return _clean(" ".join(values))


def _content_fingerprint(case: dict) -> str:
    relevant = {
        key: case.get(key)
        for key in (
            "title", "objective", "preconditions", "test_data", "steps",
            "expected_results", "postconditions", "test_type", "origin",
        )
    }
    return _clean(json.dumps(relevant, sort_keys=True, ensure_ascii=False))


def _case_text(case: dict) -> str:
    return _clean(
        " ".join(
            [
                str(case.get("title") or ""),
                str(case.get("objective") or ""),
                json.dumps(case.get("steps") or [], ensure_ascii=False),
                json.dumps(case.get("expected_results") or [], ensure_ascii=False),
            ]
        )
    )


def _analysis_obligations(inputs: dict, section_names: tuple[str, ...]) -> list[tuple[str, str]]:
    analysis = inputs.get("approved_analysis") or {}
    result = []
    for section in section_names:
        rows = analysis.get(section, []) if isinstance(analysis, dict) else []
        if not isinstance(rows, list):
            continue
        for index, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue
            item_id = str(
                item.get("id")
                or item.get("requirement_id")
                or item.get("criterion_id")
                or f"{section}-{index}"
            )
            text = str(
                item.get("description")
                or item.get("text")
                or item.get("statement")
                or ""
            )
            result.append((item_id, text))
    return result


def run_deterministic_checks(payload, inputs: dict) -> tuple[
    list[TestQualityIssue], list[MissingCoverageItem], list[DuplicateGroup]
]:
    cases = _case_rows(payload)
    issues: list[TestQualityIssue] = []
    missing_coverage: list[MissingCoverageItem] = []
    duplicate_groups: list[DuplicateGroup] = []
    catalog = source_catalog(inputs)
    evidence = _evidence_corpus(inputs)

    ids = [str(case.get("test_case_id") or "").strip() for case in cases]
    duplicate_ids = {item for item, count in Counter(ids).items() if item and count > 1}
    fingerprints: dict[str, list[str]] = defaultdict(list)

    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("test_case_id") or "").strip() or None
        label = case_id or f"case at index {index}"
        if not case_id:
            issues.append(_issue(
                ReviewCategory.MISSING_ID,
                f"{label} has no test_case_id.",
                "Assign a stable unique test_case_id.",
                auto_correctable=True,
            ))
        elif case_id in duplicate_ids:
            issues.append(_issue(
                ReviewCategory.DUPLICATE_ID,
                f"test_case_id {case_id} is used more than once.",
                "Keep the original stable ID on one case and assign unique IDs to the others.",
                case_id=case_id,
                auto_correctable=True,
            ))

        title = str(case.get("title") or "").strip()
        if not title:
            issues.append(_issue(
                ReviewCategory.MISSING_TITLE,
                f"{label} has no title.",
                "Add a concise title describing the behavior under test.",
                case_id=case_id,
                auto_correctable=True,
            ))
        elif len(title.split()) < 3 or _clean(title) in {"test case", "valid test", "verify behavior"}:
            issues.append(_issue(
                ReviewCategory.VAGUE_TITLE,
                f"{label} has a vague title: {title!r}.",
                "Describe the action, condition, and expected outcome in the title.",
                case_id=case_id,
                severity=ReviewSeverity.WARNING,
                auto_correctable=True,
            ))

        steps = case.get("steps") or []
        if not isinstance(steps, list) or not steps:
            issues.append(_issue(
                ReviewCategory.EMPTY_STEPS,
                f"{label} has no executable steps.",
                "Add ordered steps with one primary action per step.",
                case_id=case_id,
                auto_correctable=True,
            ))
        else:
            for step in steps:
                action = _clean(step.get("action") if isinstance(step, dict) else step)
                if " and then " in action or "; then " in action:
                    issues.append(_issue(
                        ReviewCategory.MULTIPLE_ACTIONS,
                        f"{label} contains multiple actions in one step: {action!r}.",
                        "Split the action into separate ordered steps and relink expected results.",
                        case_id=case_id,
                        severity=ReviewSeverity.WARNING,
                        auto_correctable=True,
                    ))

        expected_results = case.get("expected_results") or []
        if not isinstance(expected_results, list) or not expected_results:
            issues.append(_issue(
                ReviewCategory.EMPTY_EXPECTED_RESULTS,
                f"{label} has no expected results.",
                "Add observable expected results linked to authoritative sources.",
                case_id=case_id,
                auto_correctable=False,
            ))
        for result in expected_results if isinstance(expected_results, list) else []:
            row = result if isinstance(result, dict) else {"expected_result": result}
            result_text = str(row.get("expected_result") or "").strip()
            refs = row.get("source_refs") or []
            if not refs:
                issues.append(_issue(
                    ReviewCategory.MISSING_SOURCE_REFERENCE,
                    f"{label} expected result has no source reference: {result_text!r}.",
                    "Cite an authoritative/approved source or convert the behavior to an unresolved question.",
                    case_id=case_id,
                    auto_correctable=False,
                ))
            supported = False
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                key = (str(ref.get("source_type") or ""), str(ref.get("source_id") or ""))
                if key not in catalog:
                    issues.append(_issue(
                        ReviewCategory.INVALID_SOURCE_REFERENCE,
                        f"{label} cites unavailable source {key[0]}:{key[1]}.",
                        "Replace it with an authoritative Jira, confirmed clarification, or ACCEPTED KB reference.",
                        case_id=case_id,
                        source_refs=[ref],
                        auto_correctable=False,
                    ))
                if key in catalog and key[0] in {"JIRA", "CONFIRMED_CLARIFICATION", "KNOWLEDGE_BASE"}:
                    supported = True
            assumption = row.get("assumption")
            unresolved = row.get("unresolved_question")
            if not supported:
                category = (
                    ReviewCategory.UNRESOLVED_ASSUMPTION
                    if assumption or unresolved
                    else ReviewCategory.UNSUPPORTED_EXPECTED_RESULT
                )
                issues.append(_issue(
                    category,
                    f"{label} expected result is not confirmed by an authoritative/approved source: {result_text!r}.",
                    "Obtain source confirmation or remove the unsupported expected behavior.",
                    case_id=case_id,
                    source_refs=refs,
                    auto_correctable=False,
                ))

            for token in _UNSUPPORTED_NUMBER_RE.findall(result_text):
                if _clean(token) not in evidence:
                    issues.append(_issue(
                        ReviewCategory.INVENTED_AMOUNT,
                        f"{label} contains unsupported numeric/amount value {token!r} in an expected result.",
                        "Remove the value or cite a source that explicitly defines it.",
                        case_id=case_id,
                        source_refs=refs,
                        auto_correctable=False,
                    ))
            for message in _QUOTED_MESSAGE_RE.findall(result_text):
                if _clean(message) not in evidence:
                    issues.append(_issue(
                        ReviewCategory.INVENTED_MESSAGE,
                        f"{label} expects unsupported message text {message!r}.",
                        "Use source-defined message text or assert only supported observable behavior.",
                        case_id=case_id,
                        source_refs=refs,
                        auto_correctable=True,
                    ))
            if any(phrase in _clean(result_text) for phrase in _VAGUE_PHRASES):
                issues.append(_issue(
                    ReviewCategory.UNOBSERVABLE_EXPECTED_RESULT,
                    f"{label} has a vague expected result: {result_text!r}.",
                    "Replace it with a specific observable UI, API, data, or state outcome.",
                    case_id=case_id,
                    severity=ReviewSeverity.WARNING,
                    auto_correctable=True,
                ))

        if not case.get("test_data"):
            issues.append(_issue(
                ReviewCategory.MISSING_TEST_DATA,
                f"{label} has no explicit test data.",
                "Add concrete source-supported test data or an explicit unresolved question.",
                case_id=case_id,
                auto_correctable=False,
            ))

        if not any(case.get(key) for key in ("requirement_refs", "knowledge_refs", "coverage_refs", "scenario_refs")):
            issues.append(_issue(
                ReviewCategory.MISSING_TRACEABILITY,
                f"{label} has no requirement, knowledge, coverage, or scenario references.",
                "Link the case to its requirement, scenario, coverage, and approved knowledge sources.",
                case_id=case_id,
                auto_correctable=False,
            ))

        assumptions = case.get("assumptions") or []
        if assumptions:
            issues.append(_issue(
                ReviewCategory.UNRESOLVED_ASSUMPTION,
                f"{label} still contains unresolved assumptions.",
                "Confirm each assumption with an authoritative source or keep the case blocked for QA review.",
                case_id=case_id,
                auto_correctable=False,
            ))

        fingerprints[_content_fingerprint(case)].append(label)

        exclusions = list((inputs.get("test_scope_constraints") or {}).get("excluded_categories", []) or [])
        exclusions.extend(
            str(item.get("rationale") or item.get("reason") or "")
            for item in (inputs.get("coverage_model") or {}).get("out_of_scope_combinations", [])
            if isinstance(item, dict)
        )
        case_text = _case_text(case)
        for exclusion in exclusions:
            normalized = _clean(exclusion)
            if len(normalized) >= 4 and normalized in case_text:
                issues.append(_issue(
                    ReviewCategory.OUT_OF_SCOPE_CASE,
                    f"{label} appears to cover excluded scope: {exclusion!r}.",
                    "Remove the out-of-scope case or obtain an explicit scope change.",
                    case_id=case_id,
                    auto_correctable=True,
                ))
                break

    for fingerprint, group_ids in fingerprints.items():
        if fingerprint and len(group_ids) > 1:
            group_id = _stable_id("DUPLICATE_GROUP", None, fingerprint)
            duplicate_groups.append(DuplicateGroup(
                group_id=group_id,
                test_case_ids=group_ids,
                similarity=1.0,
                reason="Exact normalized test-case content is duplicated.",
            ))
            for case_id in group_ids:
                issues.append(_issue(
                    ReviewCategory.DUPLICATE_CONTENT,
                    f"{case_id} duplicates the content of {', '.join(item for item in group_ids if item != case_id)}.",
                    "Keep one case and remove or materially differentiate the duplicate.",
                    case_id=case_id if not case_id.startswith("case at index") else None,
                    auto_correctable=True,
                ))

    mapped_coverage = {
        str(ref)
        for case in cases
        for ref in (case.get("coverage_refs") or [])
    }
    for condition in (inputs.get("coverage_model") or {}).get("coverage_conditions", []):
        if not isinstance(condition, dict) or not condition.get("condition_id"):
            continue
        condition_id = str(condition["condition_id"])
        if condition.get("mandatory") is True and condition_id not in mapped_coverage:
            explanation = f"Mandatory coverage condition {condition_id} is not covered by any test case."
            issues.append(_issue(
                ReviewCategory.UNCOVERED_MANDATORY_CONDITION,
                explanation,
                "Add a source-grounded test case mapped to this mandatory coverage condition.",
                source_refs=condition.get("source_refs"),
                auto_correctable=False,
            ))
            missing_coverage.append(MissingCoverageItem(
                coverage_id=condition_id,
                coverage_type=str(condition.get("condition_type") or "MANDATORY"),
                explanation=explanation,
                source_refs=_source_refs(condition.get("source_refs")),
            ))

    mapped_requirements = {
        str(ref)
        for case in cases
        for ref in (case.get("requirement_refs") or [])
    }
    for obligation_id, text in _analysis_obligations(inputs, ("acceptance_criteria", "validations")):
        if obligation_id not in mapped_requirements:
            issues.append(_issue(
                ReviewCategory.UNCOVERED_ACCEPTANCE_CRITERION,
                f"Acceptance criterion {obligation_id} is not referenced by any test case: {text}",
                "Add or update a test case to cover this acceptance criterion.",
                auto_correctable=False,
            ))
    for rule_id, text in _analysis_obligations(inputs, ("business_rules",)):
        if rule_id not in mapped_requirements:
            issues.append(_issue(
                ReviewCategory.UNCOVERED_BUSINESS_RULE,
                f"Business rule {rule_id} is not referenced by any test case: {text}",
                "Add or update a source-grounded case for this business rule.",
                auto_correctable=False,
            ))

    deduped = {issue.issue_id: issue for issue in issues}
    return list(deduped.values()), missing_coverage, duplicate_groups
