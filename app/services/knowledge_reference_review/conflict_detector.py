from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from app.services.knowledge_reference_review.authority import source_authority_for_source_type
from app.services.knowledge_reference_review.models import (
    AuthorityPolicy,
    CandidateReference,
    ConflictSeverity,
    ConflictType,
    DetectedConflict,
    JiraStatement,
    SourceAuthority,
)

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_KEYED_NUM_RE = re.compile(r"\b(fee|amount|limit|threshold)\b\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_STATUS_PAIRS = [("enabled", "disabled"), ("active", "inactive"), ("open", "closed")]
_REQUIRED_OPTIONAL_RE = re.compile(r"\b(required|mandatory|must)\b", re.IGNORECASE)
_OPTIONAL_RE = re.compile(r"\b(optional|may|can)\b", re.IGNORECASE)


def _extract_keyed_numbers(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, number in _KEYED_NUM_RE.findall(text or ""):
        key_norm = key.strip().lower()
        if key_norm and key_norm not in values:
            values[key_norm] = number
    return values


def _id(prefix: str, payload: str) -> str:
    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_conflict(
    *,
    candidate: CandidateReference,
    jira_statement: JiraStatement,
    conflict_type: ConflictType,
    severity: ConflictSeverity,
    authoritative_source: SourceAuthority,
    recommended_action: str,
    human_confirmation_required: bool,
) -> DetectedConflict:
    payload = f"{candidate.result_id}|{jira_statement.statement_id}|{conflict_type.value}|{candidate.citation}"
    return DetectedConflict(
        conflict_id=_id("CF", payload),
        source_result_id=candidate.result_id,
        jira_statement=jira_statement.text,
        jira_source=jira_statement.source,
        kb_statement=candidate.excerpt,
        kb_source=candidate.citation,
        conflict_type=conflict_type,
        severity=severity,
        authoritative_source=authoritative_source,
        recommended_action=recommended_action,
        human_confirmation_required=human_confirmation_required,
    )


def detect_conflicts(
    *,
    candidate: CandidateReference,
    jira_statements: list[JiraStatement],
    authority_policy: AuthorityPolicy,
    accepted_references: list[dict],
) -> list[DetectedConflict]:
    conflicts: list[DetectedConflict] = []

    top_jira = jira_statements[0] if jira_statements else JiraStatement(statement_id="JIRA-EMPTY", source="jira", text="")
    authoritative = source_authority_for_source_type(candidate.source_type)

    excerpt = (candidate.excerpt or "").strip()
    jira_blob = "\n".join(item.text for item in jira_statements)

    jira_has_required = bool(_REQUIRED_OPTIONAL_RE.search(jira_blob))
    kb_has_optional = bool(_OPTIONAL_RE.search(excerpt))
    if jira_has_required and kb_has_optional:
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.CONTRADICTS_JIRA,
                severity=ConflictSeverity.CRITICAL,
                authoritative_source=SourceAuthority.CURRENT_JIRA_TICKET,
                recommended_action="Reject or mark for manual confirmation; Jira remains authoritative.",
                human_confirmation_required=True,
            )
        )

    jira_dates = {item for item in _DATE_RE.findall(jira_blob)}
    kb_dates = {item for item in _DATE_RE.findall(excerpt)}
    if jira_dates and kb_dates and jira_dates != kb_dates:
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.DATE_MISMATCH,
                severity=ConflictSeverity.HIGH,
                authoritative_source=SourceAuthority.CURRENT_JIRA_TICKET,
                recommended_action="Confirm effective date; keep Jira date unless explicitly superseded.",
                human_confirmation_required=True,
            )
        )

    jira_nums = {item for item in _NUM_RE.findall(jira_blob)}
    kb_nums = {item for item in _NUM_RE.findall(excerpt)}
    jira_keyed = _extract_keyed_numbers(jira_blob)
    kb_keyed = _extract_keyed_numbers(excerpt)

    keyed_mismatch = any(
        key in jira_keyed and key in kb_keyed and jira_keyed[key] != kb_keyed[key]
        for key in set(jira_keyed.keys()).union(kb_keyed.keys())
    )

    if keyed_mismatch or (jira_nums and kb_nums and jira_nums.isdisjoint(kb_nums)):
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.VALUE_MISMATCH,
                severity=ConflictSeverity.HIGH,
                authoritative_source=SourceAuthority.CURRENT_JIRA_TICKET,
                recommended_action="Do not propagate numeric value until human confirms.",
                human_confirmation_required=True,
            )
        )

    jira_lower = jira_blob.lower()
    kb_lower = excerpt.lower()
    for positive, negative in _STATUS_PAIRS:
        if positive in jira_lower and negative in kb_lower:
            conflicts.append(
                _build_conflict(
                    candidate=candidate,
                    jira_statement=top_jira,
                    conflict_type=ConflictType.STATUS_MISMATCH,
                    severity=ConflictSeverity.HIGH,
                    authoritative_source=SourceAuthority.CURRENT_JIRA_TICKET,
                    recommended_action="Resolve status mismatch manually before use.",
                    human_confirmation_required=True,
                )
            )
            break

    if candidate.effective_to:
        effective_to = _parse_date(candidate.effective_to)
        if effective_to and effective_to < _now():
            conflicts.append(
                _build_conflict(
                    candidate=candidate,
                    jira_statement=top_jira,
                    conflict_type=ConflictType.OUTDATED_REFERENCE,
                    severity=ConflictSeverity.MEDIUM,
                    authoritative_source=authoritative,
                    recommended_action="Mark outdated and exclude from accepted context.",
                    human_confirmation_required=False,
                )
            )

    if candidate.status.upper() in {"ARCHIVED", "SUPERSEDED", "FAILED"}:
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.OUTDATED_REFERENCE,
                severity=ConflictSeverity.MEDIUM,
                authoritative_source=authoritative,
                recommended_action="Reference is not active. Reject or mark outdated.",
                human_confirmation_required=False,
            )
        )

    for selected in accepted_references:
        if not isinstance(selected, dict):
            continue
        if str(selected.get("citation", "")).strip() == candidate.citation and str(selected.get("excerpt", "")).strip() == candidate.excerpt:
            conflicts.append(
                _build_conflict(
                    candidate=candidate,
                    jira_statement=top_jira,
                    conflict_type=ConflictType.DUPLICATE_RULE,
                    severity=ConflictSeverity.LOW,
                    authoritative_source=authoritative,
                    recommended_action="Already accepted elsewhere. Avoid duplicate context.",
                    human_confirmation_required=False,
                )
            )
            break

    if candidate.source_type.upper() in {"OBSERVED_BEHAVIOR", "UNKNOWN"} and "current behavior" in kb_lower:
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.UNSUPPORTED_BEHAVIOR,
                severity=ConflictSeverity.MEDIUM,
                authoritative_source=SourceAuthority.CURRENT_JIRA_TICKET,
                recommended_action="Do not replace Jira intent with observed behavior.",
                human_confirmation_required=True,
            )
        )

    if candidate.source_type.upper() in {"DEFECT", "HISTORICAL_DEFECT", "HISTORY"}:
        conflicts.append(
            _build_conflict(
                candidate=candidate,
                jira_statement=top_jira,
                conflict_type=ConflictType.HISTORICAL_ONLY,
                severity=ConflictSeverity.LOW,
                authoritative_source=SourceAuthority.HISTORICAL_DEFECTS,
                recommended_action="Use for context only; do not apply as current business rule.",
                human_confirmation_required=False,
            )
        )

    deduped: list[DetectedConflict] = []
    seen = set()
    for conflict in conflicts:
        key = (conflict.source_result_id, conflict.conflict_type.value, conflict.jira_source, conflict.kb_source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(conflict)

    return deduped
