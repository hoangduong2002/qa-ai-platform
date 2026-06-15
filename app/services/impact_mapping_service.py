import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.services.jira_delta_service import load_latest_change_impact_report as _load_change_report
from app.services.jira_delta_service import (
    load_latest_jira_snapshot,
)


logger = logging.getLogger(__name__)

REQUIREMENTS_ROOT = Path("requirements")

# Safety decision constants – stored in regeneration_plan["safety"]
SAFETY_PARTIAL_ALLOWED = "PARTIAL_REGENERATE_ALLOWED"
SAFETY_FULL_RECOMMENDED = "FULL_REGENERATE_RECOMMENDED"
SAFETY_MANUAL_REVIEW = "MANUAL_REVIEW_RECOMMENDED"

SAFETY_STATUS_ORDER = {
    SAFETY_PARTIAL_ALLOWED: 0,
    SAFETY_FULL_RECOMMENDED: 1,
    SAFETY_MANUAL_REVIEW: 2,
}

# Figma churn thresholds
FIGMA_CHURN_MIN_REMOVED = 2
FIGMA_CHURN_MIN_ADDED = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _root(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id


def _analysis_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "analysis"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: list[Any]) -> list[str]:
    result = []
    seen = set()

    for value in values:
        clean = _clean_id(value)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)

    return result


def _normalize_ref(value: Any) -> str:
    return _clean_id(value).replace("\\", "/").lower()


def _source_ref_tokens(change: dict) -> set[str]:
    source_type = _clean_id(change.get("source_type"))
    source_id = _clean_id(change.get("source_id"))
    tokens = {
        _normalize_ref(source_id),
        _normalize_ref(f"{source_type}:{source_id}"),
        _normalize_ref(f"{source_type}/{source_id}"),
        _normalize_ref(change.get("change_type")),
    }

    for key in [
        "screen_node_id",
        "section_id",
        "page_id",
        "file_key",
        "image_path",
        "screen_name",
        "section_name",
    ]:
        value = change.get(key)
        if value:
            tokens.add(_normalize_ref(value))
            tokens.add(_normalize_ref(f"{key}:{value}"))

    return {token for token in tokens if token}


def _extract_requirement_ids(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []

    values = []
    for key in [
        "requirement_id",
        "requirement_ids",
        "related_requirement_id",
        "related_requirement_ids",
        "related_requirements",
        "req_id",
        "id",
    ]:
        values.extend(_as_list(item.get(key)))

    return _unique(values)


def _extract_source_refs(item: Any) -> set[str]:
    refs = set()

    if not isinstance(item, dict):
        return refs

    for key in [
        "source_ref",
        "source_refs",
        "source_id",
        "source_ids",
        "source_path",
        "source_paths",
        "source_file",
        "source_files",
        "comment_id",
        "subtask_key",
        "attachment_id",
        "filename",
        "figma_node_id",
        "node_id",
        "screen_id",
        "screen_node_id",
        "section_id",
        "page_id",
        "image_path",
        "frame_image_path",
    ]:
        for value in _as_list(item.get(key)):
            if isinstance(value, dict):
                refs.update(_extract_source_refs(value))
            else:
                refs.add(_normalize_ref(value))
                refs.add(_normalize_ref(f"{key}:{value}"))

    source_type = _clean_id(item.get("source_type"))
    source_id = _clean_id(item.get("source_id"))
    if source_type and source_id:
        refs.add(_normalize_ref(f"{source_type}:{source_id}"))
        refs.add(_normalize_ref(f"{source_type}/{source_id}"))

    nested = item.get("traceability") or item.get("sources") or item.get("evidence")
    for value in _as_list(nested):
        if isinstance(value, dict):
            refs.update(_extract_source_refs(value))
        else:
            refs.add(_normalize_ref(value))

    return {ref for ref in refs if ref}


def _traceability_entries(traceability: Any) -> list[dict]:
    if isinstance(traceability, list):
        return [item for item in traceability if isinstance(item, dict)]

    if not isinstance(traceability, dict):
        return []

    for key in [
        "mappings",
        "traceability_matrix",
        "source_traceability",
        "requirement_traceability",
        "items",
        "requirements",
    ]:
        value = traceability.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return []


def _load_latest_by_candidates(candidates: list[Path], default: Any) -> Any:
    for path in candidates:
        data = _read_json(path, None)
        if data:
            return data

    return default


def load_latest_change_impact_report(ticket_id: str) -> dict:
    return _load_change_report(ticket_id) or {}


def load_latest_source_traceability(ticket_id: str) -> dict:
    analysis = _analysis_dir(ticket_id)
    candidates = [
        analysis / "source_traceability_matrix.json",
        analysis / "source_traceability.json",
        analysis / "traceability_matrix.json",
        analysis / "requirement_traceability.json",
        analysis / "requirement_evidence_index.json",
    ]
    traceability = _load_latest_by_candidates(candidates, {})

    if isinstance(traceability, dict):
        traceability.setdefault("ticket_id", ticket_id)

    return traceability if isinstance(traceability, dict) else {"ticket_id": ticket_id}


def load_latest_scenarios(ticket_id: str) -> list[dict]:
    root = _root(ticket_id)
    scenarios = _load_latest_by_candidates(
        [
            root / "scenarios" / "scenarios.json",
            root / "analysis" / "scenarios.json",
            root / "scenarios" / "approved_scenarios.json",
        ],
        [],
    )

    return scenarios if isinstance(scenarios, list) else []


def load_latest_testcases(ticket_id: str) -> list[dict]:
    root = _root(ticket_id)
    testcases = _load_latest_by_candidates(
        [
            root / "generated" / "latest_testcases.json",
            root / "testcases" / "testcases.json",
            root / "testcases" / "improved_testcases.json",
            root / "testcases" / "approved_testcases.json",
        ],
        [],
    )

    return testcases if isinstance(testcases, list) else []


def map_changes_to_requirements(changes: list[dict], traceability: dict) -> dict:
    entries = _traceability_entries(traceability)
    mappings = []
    impacted = []
    unmapped = []

    for change in changes or []:
        change_tokens = _source_ref_tokens(change)
        mapped_ids = []

        for entry in entries:
            refs = _extract_source_refs(entry)
            requirement_ids = _extract_requirement_ids(entry)

            if not refs or not requirement_ids:
                continue

            if change_tokens.intersection(refs):
                mapped_ids.extend(requirement_ids)

        mapped_ids = _unique(mapped_ids)

        if mapped_ids:
            impacted.extend(mapped_ids)
        else:
            unmapped.append(change.get("change_id") or change.get("source_id") or "")

        mappings.append(
            {
                "change_id": change.get("change_id", ""),
                "source_type": change.get("source_type", ""),
                "source_id": change.get("source_id", ""),
                "change_type": change.get("change_type", ""),
                "mapped_requirement_ids": mapped_ids,
            }
        )

    return {
        "changed_source_refs": mappings,
        "impacted_requirement_ids": _unique(impacted),
        "unmapped_change_ids": _unique(unmapped),
        "traceability_entry_count": len(entries),
    }


def _related_requirement_ids(item: dict) -> list[str]:
    return _unique(
        _as_list(item.get("related_requirement_ids"))
        + _as_list(item.get("requirement_ids"))
        + _as_list(item.get("related_requirements"))
        + _as_list(item.get("traceability"))
    )


def map_requirements_to_scenarios(requirement_ids: list[str], scenarios: list[dict]) -> list[str]:
    wanted = set(requirement_ids or [])
    impacted = []

    if not wanted:
        return []

    for scenario in scenarios or []:
        if not isinstance(scenario, dict):
            continue

        scenario_id = _clean_id(scenario.get("scenario_id") or scenario.get("id"))
        related_ids = set(_related_requirement_ids(scenario))

        if scenario_id and wanted.intersection(related_ids):
            impacted.append(scenario_id)

    return _unique(impacted)


def map_scenarios_to_testcases(scenario_ids: list[str], testcases: list[dict]) -> list[str]:
    wanted = set(scenario_ids or [])
    impacted = []

    if not wanted:
        return []

    for testcase in testcases or []:
        if not isinstance(testcase, dict):
            continue

        testcase_id = _clean_id(testcase.get("testcase_id") or testcase.get("id"))
        scenario_id = _clean_id(testcase.get("scenario_id"))

        if testcase_id and scenario_id in wanted:
            impacted.append(testcase_id)

    return _unique(impacted)


def _all_testcase_ids(testcases: list[dict]) -> list[str]:
    return _unique(
        [
            testcase.get("testcase_id") or testcase.get("id")
            for testcase in testcases or []
            if isinstance(testcase, dict)
        ]
    )


def _removed_figma_change_ids(changes: list[dict]) -> set[str]:
    return {
        _clean_id(change.get("change_id"))
        for change in changes or []
        if change.get("change_type") == "figma_screen_removed"
    }


def _has_massive_description_change(changes: list[dict], mapped: dict) -> bool:
    for change in changes or []:
        if change.get("change_type") != "description_modified":
            continue

        change_id = change.get("change_id")
        mapping = next(
            (
                item
                for item in mapped.get("changed_source_refs", [])
                if item.get("change_id") == change_id
            ),
            {},
        )

        if not mapping.get("mapped_requirement_ids"):
            return True

        if change.get("recommended_action") == "FULL_REGENERATE_RECOMMENDED":
            return True

    return False


def _confidence(changes: list[dict], mapped: dict) -> str:
    unmapped = set(mapped.get("unmapped_change_ids", []))

    if not changes:
        return "HIGH"

    if not unmapped:
        return "HIGH"

    broad_types = {
        "summary_modified",
        "description_modified",
        "acceptance_criteria_modified",
        "figma_screen_removed",
        "subtask_removed",
        "attachment_removed",
    }

    for change in changes:
        if change.get("change_id") in unmapped and change.get("change_type") in broad_types:
            return "LOW"

    return "MEDIUM"


# ──────────────────────────────────────────────
# Safety-check helpers (no LLM calls)
# ──────────────────────────────────────────────


def _description_change_ratio(change_report: dict) -> float:
    """Return the text-length change ratio for description modifications.

    Compares old/new description character counts from the underlying
    snapshots.  Returns 0.0 when the info is not available.
    """
    old_version = change_report.get("old_snapshot_version")
    new_version = change_report.get("new_snapshot_version")
    ticket_id = change_report.get("ticket_id", "")

    if not old_version or not new_version or not ticket_id:
        return 0.0

    try:
        old_snapshot = load_latest_jira_snapshot(ticket_id) if not isinstance(
            old_version, int
        ) else None
        # Prefer loading by explicit version
        from app.services.jira_delta_service import _snapshot_file

        old_path = _snapshot_file(ticket_id, int(old_version))
        new_path = _snapshot_file(ticket_id, int(new_version))
    except Exception:
        return 0.0

    def _read_len(path: Path) -> int:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return int(data.get("raw_lengths", {}).get("description_chars", 0) or 0)
        except Exception:
            return 0

    old_len = _read_len(old_path)
    new_len = _read_len(new_path)

    if old_len == 0 and new_len == 0:
        return 0.0

    if old_len == 0:
        return 1.0  # description went from empty to non-empty

    ratio = abs(new_len - old_len) / old_len
    return min(ratio, 1.0)


def _check_figma_node_id_churn(changes: list[dict]) -> str:
    """Detect Figma node-ID churn in the same section.

    If many screens are removed AND many added within the same section,
    node IDs may have been regenerated – recommend manual review.
    """
    from collections import Counter

    removed_by_section: Counter = Counter()
    added_by_section: Counter = Counter()

    for ch in changes or []:
        if not isinstance(ch, dict):
            continue
        change_type = ch.get("change_type", "")
        section = (
            f"{ch.get('file_key', '')}:"
            f"{ch.get('page_id', '')}:"
            f"{ch.get('section_id', '')}"
        )
        if change_type == "figma_screen_removed":
            removed_by_section[section] += 1
        elif change_type == "figma_screen_added":
            added_by_section[section] += 1

    for section in set(removed_by_section) | set(added_by_section):
        removed = removed_by_section.get(section, 0)
        added = added_by_section.get(section, 0)
        if removed >= FIGMA_CHURN_MIN_REMOVED and added >= FIGMA_CHURN_MIN_ADDED:
            return (
                f"Figma node ID churn detected in section '{section}': "
                f"{removed} screens removed and {added} added. "
                "Node IDs may have changed. Manual review recommended."
            )

    return ""


def _resolve_safety_status(
    *,
    changes: list[dict],
    mapped: dict,
    confidence: str,
    major_change_reason: str,
    figma_churn_reason: str,
) -> tuple[str, list[str]]:
    """Determine overall safety status and collect human-readable reasons.

    Returns (status, reasons_list).
    """
    reasons: list[str] = []

    # 1 – low confidence block
    if confidence == "LOW":
        reasons.append(
            "Impact confidence is LOW; partial regeneration is not safe. "
            "Run a full regenerate instead."
        )

    # 2 – major description change
    if major_change_reason:
        reasons.append(major_change_reason)

    # 3 – missing traceability
    unmapped = mapped.get("unmapped_change_ids", [])
    if unmapped:
        reasons.append(
            f"{len(unmapped)} changed source(s) cannot be mapped to any "
            f"requirement/scenario/testcase: {', '.join(unmapped[:5])}"
            f"{'...' if len(unmapped) > 5 else ''}"
        )

    # 4 – Figma node-id churn
    if figma_churn_reason:
        reasons.append(figma_churn_reason)

    if not reasons:
        return SAFETY_PARTIAL_ALLOWED, reasons

    # Determine severity: if any reason is MANUAL_REVIEW level, that wins
    highest = SAFETY_FULL_RECOMMENDED
    for ch in changes or []:
        if not isinstance(ch, dict):
            continue
        action = ch.get("recommended_action", "")
        if action == "MANUAL_REVIEW_RECOMMENDED":
            highest = SAFETY_MANUAL_REVIEW
            break

    if figma_churn_reason:
        highest = SAFETY_MANUAL_REVIEW

    return highest, reasons


def build_regeneration_plan(
    ticket_id: str,
    change_report: dict,
    traceability: dict,
    scenarios: list[dict],
    testcases: list[dict],
) -> dict:
    changes = change_report.get("changes", []) if isinstance(change_report, dict) else []
    mapped = map_changes_to_requirements(changes, traceability)
    impacted_requirement_ids = mapped["impacted_requirement_ids"]
    impacted_scenario_ids = map_requirements_to_scenarios(impacted_requirement_ids, scenarios)
    impacted_testcase_ids = map_scenarios_to_testcases(impacted_scenario_ids, testcases)
    deprecated_candidate_testcase_ids = []
    removed_change_ids = _removed_figma_change_ids(changes)

    if removed_change_ids:
        removed_requirement_ids = []
        for mapping in mapped["changed_source_refs"]:
            if mapping.get("change_id") in removed_change_ids:
                removed_requirement_ids.extend(mapping.get("mapped_requirement_ids", []))

        removed_scenario_ids = map_requirements_to_scenarios(
            _unique(removed_requirement_ids),
            scenarios,
        )
        deprecated_candidate_testcase_ids = map_scenarios_to_testcases(
            removed_scenario_ids,
            testcases,
        )

    all_testcase_ids = set(_all_testcase_ids(testcases))
    impacted_set = set(impacted_testcase_ids)
    deprecated_set = set(deprecated_candidate_testcase_ids)
    confidence = _confidence(changes, mapped)
    reason = ""

    if _has_massive_description_change(changes, mapped):
        confidence = "LOW"
        reason = "Description changed without direct requirement traceability; full regeneration is recommended."
    elif mapped.get("unmapped_change_ids"):
        reason = "Some changed sources have no direct traceability mapping."
    elif not scenarios or not testcases:
        reason = "Latest scenarios or test cases are not available yet."

    can_partial_regenerate = confidence != "LOW" and not _has_massive_description_change(changes, mapped)

    # ── Safety checks (no LLM) ──────────────────────────────────────
    major_change_ratio = _description_change_ratio(change_report)
    threshold = settings.INCREMENTAL_MAJOR_CHANGE_THRESHOLD
    major_change_reason = ""
    if major_change_ratio > threshold:
        major_change_reason = (
            f"Description change ratio ({major_change_ratio:.2f}) exceeds "
            f"threshold ({threshold:.2f}). Full regeneration recommended."
        )
        confidence = "LOW"
        can_partial_regenerate = False
        if not reason:
            reason = major_change_reason

    figma_churn_reason = _check_figma_node_id_churn(changes)
    safety_status, safety_reasons = _resolve_safety_status(
        changes=changes,
        mapped=mapped,
        confidence=confidence,
        major_change_reason=major_change_reason,
        figma_churn_reason=figma_churn_reason,
    )

    return {
        "ticket_id": ticket_id,
        "created_at": _utc_now(),
        "plan_version": _get_next_plan_version(ticket_id),
        "source_snapshot_version": change_report.get("new_snapshot_version"),
        "change_report_version": change_report.get("report_version"),
        "changed_source_refs": mapped["changed_source_refs"],
        "impacted_requirement_ids": impacted_requirement_ids,
        "impacted_scenario_ids": impacted_scenario_ids,
        "impacted_testcase_ids": impacted_testcase_ids,
        "unchanged_testcase_ids": sorted(all_testcase_ids - impacted_set - deprecated_set),
        "deprecated_candidate_testcase_ids": deprecated_candidate_testcase_ids,
        "impact_confidence": confidence,
        "can_partial_regenerate": can_partial_regenerate,
        "reason_if_full_regenerate_required": "" if can_partial_regenerate else reason,
        "notes": {
            "unmapped_change_ids": mapped.get("unmapped_change_ids", []),
            "traceability_entry_count": mapped.get("traceability_entry_count", 0),
            "scenario_count": len(scenarios or []),
            "testcase_count": len(testcases or []),
        },
        # ── Safety block ────────────────────────────────────────────
        "safety": {
            "ticket_level_lock": True,
            "low_confidence_block": confidence == "LOW" or not can_partial_regenerate,
            "major_change_detected": bool(major_change_reason),
            "major_change_ratio": round(major_change_ratio, 4),
            "major_change_threshold": threshold,
            "missing_traceability": bool(mapped.get("unmapped_change_ids")),
            "unmapped_change_count": len(mapped.get("unmapped_change_ids", [])),
            "removed_source_strategy": "DeprecatedCandidate",
            "figma_node_id_churn": bool(figma_churn_reason),
            "figma_churn_reason": figma_churn_reason,
            "provider_safety": "ok",
            "overall_status": safety_status,
            "safety_reasons": safety_reasons,
        },
    }


def _get_next_plan_version(ticket_id: str) -> int:
    max_version = 0
    analysis = _analysis_dir(ticket_id)

    if analysis.exists():
        for path in analysis.glob("regeneration_plan_v*.json"):
            match = re.match(r"regeneration_plan_v(\d+)\.json$", path.name)
            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def _plan_file(ticket_id: str, version: int, suffix: str) -> Path:
    return _analysis_dir(ticket_id) / f"regeneration_plan_v{version}.{suffix}"


def _latest_plan_file(ticket_id: str) -> Path:
    return _analysis_dir(ticket_id) / "latest_regeneration_plan.json"


def _plan_markdown(plan: dict) -> str:
    safety = plan.get("safety", {})
    lines = [
        f"# Regeneration Plan: {plan.get('ticket_id', '')}",
        "",
        f"- Plan version: {plan.get('plan_version')}",
        f"- Change report version: {plan.get('change_report_version')}",
        f"- Source snapshot version: {plan.get('source_snapshot_version')}",
        f"- Impact confidence: {plan.get('impact_confidence')}",
        f"- Partial regenerate allowed: {plan.get('can_partial_regenerate')}",
        f"- Impacted requirements: {len(plan.get('impacted_requirement_ids', []))}",
        f"- Impacted scenarios: {len(plan.get('impacted_scenario_ids', []))}",
        f"- Impacted test cases: {len(plan.get('impacted_testcase_ids', []))}",
        "",
        "## Safety",
        "",
        f"- Overall status: {safety.get('overall_status', 'N/A')}",
        f"- Low confidence block: {safety.get('low_confidence_block', False)}",
        f"- Major change detected: {safety.get('major_change_detected', False)}",
        f"- Major change ratio: {safety.get('major_change_ratio', 0)}",
        f"- Missing traceability: {safety.get('missing_traceability', False)}",
        f"- Figma node ID churn: {safety.get('figma_node_id_churn', False)}",
        f"- Removed source strategy: {safety.get('removed_source_strategy', 'N/A')}",
        "",
    ]

    safety_reasons = safety.get("safety_reasons", [])
    if safety_reasons:
        lines.append("### Safety Reasons")
        lines.append("")
        for r in safety_reasons:
            lines.append(f"- {r}")
        lines.append("")

    reason = plan.get("reason_if_full_regenerate_required")
    if reason:
        lines.extend(["## Full Regeneration Reason", "", reason, ""])

    lines.extend(["## Impacted IDs", ""])
    for key in [
        "impacted_requirement_ids",
        "impacted_scenario_ids",
        "impacted_testcase_ids",
        "deprecated_candidate_testcase_ids",
    ]:
        values = plan.get(key, [])
        lines.append(f"- {key}: {', '.join(values) if values else 'None'}")

    lines.extend(["", "## Changed Sources", ""])
    for item in plan.get("changed_source_refs", []):
        mapped = item.get("mapped_requirement_ids") or []
        lines.append(
            f"- {item.get('change_id')}: {item.get('change_type')} "
            f"{item.get('source_type')}/{item.get('source_id')} -> "
            f"{', '.join(mapped) if mapped else 'UNMAPPED'}"
        )

    return "\n".join(lines).strip() + "\n"


def save_regeneration_plan(ticket_id: str, plan: dict) -> dict:
    version = int(plan.get("plan_version") or _get_next_plan_version(ticket_id))
    plan["ticket_id"] = ticket_id
    plan["plan_version"] = version

    json_file = _plan_file(ticket_id, version, "json")
    markdown_file = _plan_file(ticket_id, version, "md")
    latest_file = _latest_plan_file(ticket_id)

    _write_json(json_file, plan)
    markdown_file.parent.mkdir(parents=True, exist_ok=True)
    markdown_file.write_text(_plan_markdown(plan), encoding="utf-8")
    _write_json(latest_file, plan)

    return {
        "plan_version": version,
        "plan_path": str(json_file),
        "plan_markdown_path": str(markdown_file),
        "latest_plan_path": str(latest_file),
    }


def load_latest_regeneration_plan(ticket_id: str) -> dict:
    return _read_json(_latest_plan_file(ticket_id), {}) or {}


def build_and_save_regeneration_plan(ticket_id: str) -> dict:
    started = time.time()
    analysis_dir = _analysis_dir(ticket_id)
    change_report_path = analysis_dir / "latest_change_impact_report.json"
    plan_path = _latest_plan_file(ticket_id)
    impacted_requirement_count = 0
    impacted_scenario_count = 0
    impacted_testcase_count = 0

    def log_build_event(level: int, message: str) -> None:
        logger.log(
            level,
            message,
            extra={
                "ticket_id": ticket_id,
                "action": "build_regeneration_plan",
                "change_report_path": str(change_report_path),
                "plan_path": str(plan_path),
                "impacted_requirement_count": impacted_requirement_count,
                "impacted_scenario_count": impacted_scenario_count,
                "impacted_testcase_count": impacted_testcase_count,
                "duration_ms": int((time.time() - started) * 1000),
            },
        )

    change_report = load_latest_change_impact_report(ticket_id)
    if not change_report:
        log_build_event(
            logging.WARNING,
            "Build regeneration plan missing change impact report",
        )
        raise ValueError(
            "No Jira change impact report found. Please run Sync Jira Changes first."
        )

    traceability = load_latest_source_traceability(ticket_id)
    scenarios = load_latest_scenarios(ticket_id)
    testcases = load_latest_testcases(ticket_id)

    if not scenarios or not testcases:
        log_build_event(
            logging.WARNING,
            "Build regeneration plan missing scenarios or testcases",
        )
        raise ValueError(
            "No existing scenarios/testcases found. Run full generation before incremental regeneration."
        )

    if not _traceability_entries(traceability):
        log_build_event(
            logging.WARNING,
            "Build regeneration plan missing traceability",
        )
        raise ValueError(
            "No traceability/source references found. Cannot build partial regeneration plan."
        )

    plan = build_regeneration_plan(
        ticket_id=ticket_id,
        change_report=change_report,
        traceability=traceability,
        scenarios=scenarios,
        testcases=testcases,
    )
    save_result = save_regeneration_plan(ticket_id, plan)
    plan_path = Path(save_result.get("latest_plan_path") or plan_path)
    impacted_requirement_count = len(plan.get("impacted_requirement_ids", []))
    impacted_scenario_count = len(plan.get("impacted_scenario_ids", []))
    impacted_testcase_count = len(plan.get("impacted_testcase_ids", []))

    log_build_event(logging.INFO, "Built regeneration plan")

    return {
        **save_result,
        "ticket_id": ticket_id,
        "impacted_requirement_count": impacted_requirement_count,
        "impacted_scenario_count": impacted_scenario_count,
        "impacted_testcase_count": impacted_testcase_count,
        "impact_confidence": plan.get("impact_confidence"),
        "can_partial_regenerate": plan.get("can_partial_regenerate"),
        "reason_if_full_regenerate_required": plan.get("reason_if_full_regenerate_required", ""),
    }
