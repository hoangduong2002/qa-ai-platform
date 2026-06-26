import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.impact_mapping_service import (
    SAFETY_FULL_RECOMMENDED,
    SAFETY_MANUAL_REVIEW,
    SAFETY_PARTIAL_ALLOWED,
    load_latest_regeneration_plan,
    load_latest_scenarios,
    load_latest_testcases,
)
from app.services.llm_router_service import (
    TASK_SCENARIO_GENERATION,
    TASK_TESTCASE_GENERATION,
    call_text_llm,
)
from app.services.testcase_automation_classifier import (
    classify_testcases_automation,
)
from app.utils.llm_json import parse_json


REQUIREMENTS_ROOT = Path("requirements")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _root(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id


def _analysis_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "analysis"


def _generated_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "generated"


def _logs_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "logs"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _clean(value: Any) -> str:
    return str(value or "").strip()


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


def _unique(values: list[Any]) -> list[str]:
    result = []
    seen = set()

    for value in values:
        clean = _clean(value)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)

    return result


def _related_requirement_ids(item: dict) -> list[str]:
    return _unique(
        _as_list(item.get("related_requirement_ids"))
        + _as_list(item.get("requirement_ids"))
        + _as_list(item.get("related_requirements"))
        + _as_list(item.get("traceability"))
    )


def _scenario_id(item: dict) -> str:
    return _clean(item.get("scenario_id") or item.get("id"))


def _testcase_id(item: dict) -> str:
    return _clean(item.get("testcase_id") or item.get("id"))


def _testcase_scenario_id(item: dict) -> str:
    return _clean(item.get("related_scenario_id") or item.get("scenario_id"))


def _requirement_id(item: dict) -> str:
    return _clean(item.get("requirement_id") or item.get("id") or item.get("item_id"))


def _next_version(ticket_id: str) -> int:
    max_version = 0
    generated = _generated_dir(ticket_id)

    if generated.exists():
        for path in generated.glob("incremental_scenarios_v*.json"):
            match = re.match(r"incremental_scenarios_v(\d+)\.json$", path.name)
            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def _next_testcase_version(ticket_id: str) -> int:
    max_version = 0
    generated = _generated_dir(ticket_id)

    if generated.exists():
        for path in generated.glob("incremental_testcases_v*.json"):
            match = re.match(r"incremental_testcases_v(\d+)\.json$", path.name)
            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def _latest_incremental_requirement_items(ticket_id: str) -> list[dict]:
    analysis = _analysis_dir(ticket_id)
    latest = None
    latest_version = 0

    if analysis.exists():
        for path in analysis.glob("incremental_requirement_items_v*.json"):
            match = re.match(r"incremental_requirement_items_v(\d+)\.json$", path.name)
            if match and int(match.group(1)) > latest_version:
                latest = path
                latest_version = int(match.group(1))

    items = _read_json(latest, []) if latest else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _latest_incremental_scenarios(ticket_id: str) -> list[dict]:
    generated = _generated_dir(ticket_id)
    latest = None
    latest_version = 0

    if generated.exists():
        for path in generated.glob("incremental_scenarios_v*.json"):
            match = re.match(r"incremental_scenarios_v(\d+)\.json$", path.name)
            if match and int(match.group(1)) > latest_version:
                latest = path
                latest_version = int(match.group(1))

    scenarios = _read_json(latest, []) if latest else []
    return [item for item in scenarios if isinstance(item, dict)] if isinstance(scenarios, list) else []


def _max_existing_scenario_number(old_scenarios: list[dict]) -> int:
    max_number = 0

    for scenario in old_scenarios or []:
        match = re.match(r"SC(\d+)$", _scenario_id(scenario))
        if match:
            max_number = max(max_number, int(match.group(1)))

    return max_number


def _next_scenario_id_factory(old_scenarios: list[dict]):
    counter = _max_existing_scenario_number(old_scenarios)

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"SC{counter:03d}"

    return next_id


def _max_existing_testcase_number(old_testcases: list[dict]) -> int:
    max_number = 0

    for testcase in old_testcases or []:
        match = re.match(r"TC(\d+)$", _testcase_id(testcase))
        if match:
            max_number = max(max_number, int(match.group(1)))

    return max_number


def _next_testcase_id_factory(old_testcases: list[dict]):
    counter = _max_existing_testcase_number(old_testcases)

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"TC{counter:03d}"

    return next_id


def _impacted_requirement_items(items: list[dict]) -> list[dict]:
    return [
        item
        for item in items or []
        if isinstance(item, dict)
        and item.get("change_status") in {"New", "Updated"}
    ]


def _deprecated_requirement_ids(regeneration_plan: dict, items: list[dict]) -> set[str]:
    result = {
        _requirement_id(item)
        for item in items or []
        if isinstance(item, dict) and item.get("change_status") == "DeprecatedCandidate"
    }

    for ref in regeneration_plan.get("changed_source_refs", []) or []:
        if not isinstance(ref, dict):
            continue
        if "removed" in _clean(ref.get("change_type")).lower():
            result.update(_as_list(ref.get("mapped_requirement_ids")))

    return {item for item in result if item}


def _scenarios_for_requirements(scenarios: list[dict], requirement_ids: set[str]) -> list[dict]:
    result = []

    if not requirement_ids:
        return result

    for scenario in scenarios or []:
        if not isinstance(scenario, dict):
            continue
        if requirement_ids.intersection(_related_requirement_ids(scenario)):
            result.append(scenario)

    return result


def _impacted_scenarios(scenarios: list[dict]) -> list[dict]:
    return [
        scenario
        for scenario in scenarios or []
        if isinstance(scenario, dict)
        and scenario.get("change_status") in {"New", "Updated"}
    ]


def _testcases_for_scenarios(testcases: list[dict], scenario_ids: set[str]) -> list[dict]:
    result = []

    if not scenario_ids:
        return result

    for testcase in testcases or []:
        if not isinstance(testcase, dict):
            continue
        if _testcase_scenario_id(testcase) in scenario_ids:
            result.append(testcase)

    return result


def _prompt(
    ticket_id: str,
    regeneration_plan: dict,
    incremental_requirement_items: list[dict],
    old_impacted_scenarios: list[dict],
) -> str:
    return f"""
You generate test scenarios only for changed requirement items.

Return STRICT JSON object only. No markdown. No prose outside JSON.

JSON schema:
{{
  "scenarios": [
    {{
      "scenario_id": "SC999 or empty if unknown",
      "title": "",
      "description": "",
      "related_requirement_ids": ["REQ-001"],
      "source_refs": ["source reference"],
      "change_status": "New | Updated",
      "previous_scenario_id": "SC001 or empty",
      "related_change_ids": ["CHG-001"],
      "source_snapshot_version": {json.dumps(regeneration_plan.get("source_snapshot_version"))}
    }}
  ]
}}

Rules:
- Generate scenarios only for requirement items with change_status New or Updated.
- New requirement item -> generate new scenarios with change_status "New".
- Updated requirement item -> regenerate only scenarios linked to that requirement with change_status "Updated".
- Do not include scenarios for unchanged requirements.
- Do not generate test cases.
- Every scenario must include related_requirement_ids, source_refs, change_status, previous_scenario_id, related_change_ids, and source_snapshot_version.
- If an updated scenario replaces an existing one, set previous_scenario_id to that existing scenario_id when clear.
- Use concise scenario descriptions suitable for QA design.

Ticket ID: {ticket_id}

Regeneration plan:
{json.dumps({
    "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
    "change_report_version": regeneration_plan.get("change_report_version"),
    "impact_confidence": regeneration_plan.get("impact_confidence"),
    "impacted_requirement_ids": regeneration_plan.get("impacted_requirement_ids", []),
    "impacted_scenario_ids": regeneration_plan.get("impacted_scenario_ids", []),
}, ensure_ascii=False, indent=2)}

Incremental requirement items:
{json.dumps(incremental_requirement_items, ensure_ascii=False, indent=2)}

Existing impacted scenarios that may need replacement:
{json.dumps(old_impacted_scenarios, ensure_ascii=False, indent=2)}
""".strip()


def _assert_json_candidate(content: str, raw_path: str) -> None:
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Incremental scenario generation returned an empty response.")

    lowered = content.strip().lower()
    if (
        lowered.startswith("[skipped]")
        or lowered.startswith("[error]")
        or "provider blocked" in lowered
        or "requires llm" in lowered
    ):
        raise RuntimeError("Incremental scenario generation did not receive valid LLM JSON.")

    if content.strip()[0] not in "{[":
        raise RuntimeError(
            "Incremental scenario generation returned non-JSON text. "
            f"Check raw response at {raw_path}."
        )


def _normalize_generated_scenarios(
    generated: Any,
    *,
    old_scenarios: list[dict],
    regeneration_plan: dict,
    incremental_requirement_items: list[dict],
) -> list[dict]:
    if isinstance(generated, dict):
        scenarios = generated.get("scenarios") or generated.get("test_scenarios") or []
    elif isinstance(generated, list):
        scenarios = generated
    else:
        scenarios = []

    next_scenario_id = _next_scenario_id_factory(old_scenarios)
    impacted_by_requirement = {
        requirement_id: _scenarios_for_requirements(old_scenarios, {requirement_id})
        for requirement_id in {
            _requirement_id(item)
            for item in incremental_requirement_items
            if isinstance(item, dict)
        }
    }
    item_by_requirement = {
        _requirement_id(item): item
        for item in incremental_requirement_items
        if isinstance(item, dict) and _requirement_id(item)
    }
    normalized = []

    for item in scenarios or []:
        if not isinstance(item, dict):
            continue

        scenario = dict(item)
        related_requirement_ids = _unique(_as_list(scenario.get("related_requirement_ids")))
        if not related_requirement_ids:
            related_requirement_ids = _unique(_as_list(scenario.get("requirement_ids")))
        if not related_requirement_ids:
            continue

        related_items = [
            item_by_requirement[requirement_id]
            for requirement_id in related_requirement_ids
            if requirement_id in item_by_requirement
        ]
        related_statuses = {item.get("change_status") for item in related_items}
        change_status = _clean(scenario.get("change_status"))

        if change_status not in {"New", "Updated"}:
            change_status = "New" if "New" in related_statuses else "Updated"

        previous_scenario_id = _clean(scenario.get("previous_scenario_id"))
        if change_status == "Updated" and not previous_scenario_id:
            old_matches = []
            for requirement_id in related_requirement_ids:
                old_matches.extend(impacted_by_requirement.get(requirement_id, []))
            if old_matches:
                previous_scenario_id = _scenario_id(old_matches[0])

        scenario_id = _clean(scenario.get("scenario_id"))
        if not scenario_id or scenario_id == previous_scenario_id:
            scenario_id = next_scenario_id()

        related_change_ids = []
        source_refs = []
        for related_item in related_items:
            related_change_ids.extend(_as_list(related_item.get("related_change_ids")))
            source_refs.extend(_as_list(related_item.get("source_refs")))

        scenario["scenario_id"] = scenario_id
        scenario["related_requirement_ids"] = related_requirement_ids
        scenario["source_refs"] = _unique(_as_list(scenario.get("source_refs")) + source_refs)
        scenario["change_status"] = change_status
        scenario["previous_scenario_id"] = previous_scenario_id
        scenario["related_change_ids"] = _unique(
            _as_list(scenario.get("related_change_ids")) + related_change_ids
        )
        scenario["source_snapshot_version"] = regeneration_plan.get("source_snapshot_version")
        scenario["traceability"] = ", ".join(related_requirement_ids)
        normalized.append(scenario)

    return normalized


# ──────────────────────────────────────────────
# Centralised safety gate (no LLM calls)
# ──────────────────────────────────────────────


def check_regeneration_safety(regeneration_plan: dict) -> None:
    """Raise RuntimeError if the plan's safety rules forbid partial regeneration.

    Inspects the ``safety`` block embedded in the regeneration plan.
    This function does **not** call any LLM.
    """
    safety = regeneration_plan.get("safety", {})
    overall_status = safety.get("overall_status", SAFETY_PARTIAL_ALLOWED)
    reasons = safety.get("safety_reasons", [])

    if overall_status == SAFETY_PARTIAL_ALLOWED:
        return  # safe to proceed

    if overall_status == SAFETY_FULL_RECOMMENDED:
        msg = (
            "Regeneration plan safety check blocked partial regeneration.\n"
            "Status: FULL_REGENERATE_RECOMMENDED.\n"
        )
        if reasons:
            msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
        msg += "\n\nRun a full regenerate instead."
        raise RuntimeError(msg)

    if overall_status == SAFETY_MANUAL_REVIEW:
        msg = (
            "Regeneration plan safety check blocked partial regeneration.\n"
            "Status: MANUAL_REVIEW_RECOMMENDED.\n"
        )
        if reasons:
            msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
        msg += "\n\nManual review is required before proceeding."
        raise RuntimeError(msg)


def regenerate_impacted_scenarios(
    ticket_id: str,
    regeneration_plan: dict,
    incremental_requirement_items: list[dict],
    ai_mode: str | None,
    source_channel: str | None = None,
) -> list[dict]:
    check_regeneration_safety(regeneration_plan)

    impacted_items = _impacted_requirement_items(incremental_requirement_items)
    if not impacted_items:
        return []

    old_scenarios = load_latest_scenarios(ticket_id)
    impacted_requirement_ids = {
        _requirement_id(item)
        for item in impacted_items
        if _requirement_id(item)
    }
    old_impacted_scenarios = _scenarios_for_requirements(
        old_scenarios,
        impacted_requirement_ids,
    )
    prompt = _prompt(
        ticket_id=ticket_id,
        regeneration_plan=regeneration_plan,
        incremental_requirement_items=impacted_items,
        old_impacted_scenarios=old_impacted_scenarios,
    )
    version = _next_version(ticket_id)
    raw_path = _logs_dir(ticket_id) / f"incremental_scenarios_v{version}_raw.txt"

    try:
        content = call_text_llm(
            task_type=TASK_SCENARIO_GENERATION,
            prompt=prompt,
            ai_mode=ai_mode,
            source_channel=source_channel,
            format="json",
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as error:
        raise RuntimeError(f"Incremental scenario generation failed: {error}") from error

    raw_response_path = _write_text(raw_path, content)

    try:
        _assert_json_candidate(content, raw_response_path)
        parsed = parse_json(content, label="incremental scenario generation response")
    except Exception as error:
        parse_error_path = _write_text(
            _logs_dir(ticket_id) / f"incremental_scenarios_v{version}_parse_error.txt",
            (
                "Incremental scenario generation parse failure.\n"
                f"Error: {error}\n"
                f"Raw response path: {raw_response_path}\n"
            ),
        )
        raise RuntimeError(
            "Incremental scenario generation response failed to parse JSON. "
            f"Check raw response at {raw_response_path} and parse error at {parse_error_path}."
        ) from error

    return _normalize_generated_scenarios(
        parsed,
        old_scenarios=old_scenarios,
        regeneration_plan=regeneration_plan,
        incremental_requirement_items=impacted_items,
    )


def merge_scenarios(
    old_scenarios: list[dict],
    new_scenarios: list[dict],
    regeneration_plan: dict,
) -> list[dict]:
    impacted_requirement_ids = set(regeneration_plan.get("impacted_requirement_ids", []) or [])
    deprecated_requirement_ids = _deprecated_requirement_ids(regeneration_plan, [])
    replaced_ids = {
        _clean(scenario.get("previous_scenario_id"))
        for scenario in new_scenarios or []
        if isinstance(scenario, dict) and scenario.get("previous_scenario_id")
    }
    merged = []

    for old in old_scenarios or []:
        if not isinstance(old, dict):
            continue

        item = dict(old)
        scenario_id = _scenario_id(item)
        related_ids = set(_related_requirement_ids(item))

        if scenario_id in replaced_ids:
            item["change_status"] = "Replaced"
        elif deprecated_requirement_ids.intersection(related_ids):
            item["change_status"] = "DeprecatedCandidate"
        elif impacted_requirement_ids.intersection(related_ids):
            item["change_status"] = "Replaced" if scenario_id in replaced_ids else "Unchanged"
        else:
            item["change_status"] = "Unchanged"

        merged.append(item)

    existing_ids = {_scenario_id(item) for item in merged if isinstance(item, dict)}
    next_scenario_id = _next_scenario_id_factory(merged)

    for scenario in new_scenarios or []:
        if not isinstance(scenario, dict):
            continue

        item = dict(scenario)
        scenario_id = _scenario_id(item)

        if not scenario_id or scenario_id in existing_ids:
            scenario_id = next_scenario_id()
            item["scenario_id"] = scenario_id

        existing_ids.add(scenario_id)
        merged.append(item)

    return merged


def _merge_report(
    ticket_id: str,
    version: int,
    old_scenarios: list[dict],
    new_scenarios: list[dict],
    merged_scenarios: list[dict],
    regeneration_plan: dict,
) -> dict:
    counts: dict[str, int] = {}
    for scenario in merged_scenarios:
        status = scenario.get("change_status", "Unchanged")
        counts[status] = counts.get(status, 0) + 1

    return {
        "ticket_id": ticket_id,
        "version": version,
        "created_at": _utc_now(),
        "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
        "change_report_version": regeneration_plan.get("change_report_version"),
        "regeneration_plan_version": regeneration_plan.get("plan_version"),
        "old_scenario_count": len(old_scenarios or []),
        "new_scenario_count": len(new_scenarios or []),
        "merged_scenario_count": len(merged_scenarios or []),
        "change_status_counts": counts,
        "impacted_requirement_ids": regeneration_plan.get("impacted_requirement_ids", []),
        "impacted_scenario_ids": regeneration_plan.get("impacted_scenario_ids", []),
        "new_scenario_ids": [
            scenario.get("scenario_id")
            for scenario in new_scenarios
            if isinstance(scenario, dict) and scenario.get("scenario_id")
        ],
        "replaced_scenario_ids": [
            scenario.get("previous_scenario_id")
            for scenario in new_scenarios
            if isinstance(scenario, dict) and scenario.get("previous_scenario_id")
        ],
    }


def save_incremental_scenarios(
    ticket_id: str,
    merged_scenarios: list[dict],
    new_scenarios: list[dict],
    old_scenarios: list[dict],
    regeneration_plan: dict,
) -> dict:
    version = _next_version(ticket_id)
    scenarios_path = _write_json(
        _generated_dir(ticket_id) / f"incremental_scenarios_v{version}.json",
        merged_scenarios,
    )
    report = _merge_report(
        ticket_id,
        version,
        old_scenarios,
        new_scenarios,
        merged_scenarios,
        regeneration_plan,
    )
    report_path = _write_json(
        _analysis_dir(ticket_id) / f"incremental_scenario_merge_report_v{version}.json",
        report,
    )

    return {
        "version": version,
        "scenarios_path": scenarios_path,
        "merge_report_path": report_path,
        "new_scenario_count": len(new_scenarios or []),
        "merged_scenario_count": len(merged_scenarios or []),
        "change_status_counts": report["change_status_counts"],
    }


def run_incremental_scenario_generation(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> dict:
    regeneration_plan = load_latest_regeneration_plan(ticket_id)
    if not regeneration_plan:
        raise ValueError("No regeneration plan found. Build regeneration plan first.")

    incremental_requirement_items = _latest_incremental_requirement_items(ticket_id)
    if not incremental_requirement_items:
        raise ValueError("No incremental requirement items found. Analyze changed sources first.")

    old_scenarios = load_latest_scenarios(ticket_id)
    new_scenarios = regenerate_impacted_scenarios(
        ticket_id=ticket_id,
        regeneration_plan=regeneration_plan,
        incremental_requirement_items=incremental_requirement_items,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )
    merged_scenarios = merge_scenarios(
        old_scenarios=old_scenarios,
        new_scenarios=new_scenarios,
        regeneration_plan=regeneration_plan,
    )

    return save_incremental_scenarios(
        ticket_id=ticket_id,
        merged_scenarios=merged_scenarios,
        new_scenarios=new_scenarios,
        old_scenarios=old_scenarios,
        regeneration_plan=regeneration_plan,
    )


def _testcase_prompt(
    ticket_id: str,
    regeneration_plan: dict,
    incremental_scenarios: list[dict],
    old_impacted_testcases: list[dict],
) -> str:
    return f"""
You generate test cases only for impacted scenarios.

Return STRICT JSON object only. No markdown. No prose outside JSON.

JSON schema:
{{
  "testcases": [
    {{
      "testcase_id": "TC999 or empty if unknown",
      "title": "",
      "preconditions": [],
      "steps": [],
      "expected_result": "",
      "related_requirement_ids": ["REQ-001"],
      "related_scenario_id": "SC001",
      "source_refs": ["source reference"],
      "change_status": "New | Updated",
      "previous_testcase_id": "TC001 or empty",
      "related_change_ids": ["CHG-001"],
      "source_snapshot_version": {json.dumps(regeneration_plan.get("source_snapshot_version"))},
      "execution_type": "AUTOMATION | MANUAL | HYBRID",
      "automation_candidate": true,
      "automation_tool": "Playwright",
      "automation_priority": "High | Medium | Low | Not Applicable",
      "automation_reason": "",
      "automation_blockers": [],
      "manual_reason": ""
    }}
  ]
}}

Rules:
- Generate test cases only for scenarios with change_status New or Updated.
- If a scenario is New, generated test cases should use change_status "New".
- If a scenario is Updated, generated test cases should use change_status "Updated".
- Do not include test cases for unchanged scenarios.
- Do not delete or rewrite old unaffected test cases.
- If an updated test case replaces an existing one, set previous_testcase_id to that old testcase_id when clear.
- Preserve scenario links using related_scenario_id.
- Also include scenario_id with the same value as related_scenario_id for compatibility.
- Include source_refs, related_change_ids, related_requirement_ids, and source_snapshot_version for every item.
- Classify every test case for Playwright automation.
- Use AUTOMATION when browser UI execution is reliable and assertions are deterministic.
- Use MANUAL when the case requires human judgment, subjective UX review, external confirmation, physical device, visual-only validation, unstable data, or manual approval.
- Use HYBRID when browser steps can be automated but final verification requires manual review.

Ticket ID: {ticket_id}

Regeneration plan:
{json.dumps({
    "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
    "change_report_version": regeneration_plan.get("change_report_version"),
    "impact_confidence": regeneration_plan.get("impact_confidence"),
    "impacted_requirement_ids": regeneration_plan.get("impacted_requirement_ids", []),
    "impacted_scenario_ids": regeneration_plan.get("impacted_scenario_ids", []),
    "impacted_testcase_ids": regeneration_plan.get("impacted_testcase_ids", []),
}, ensure_ascii=False, indent=2)}

Incremental scenarios:
{json.dumps(incremental_scenarios, ensure_ascii=False, indent=2)}

Existing impacted test cases that may need replacement:
{json.dumps(old_impacted_testcases, ensure_ascii=False, indent=2)}
""".strip()


def _normalize_list_field(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_generated_testcases(
    generated: Any,
    *,
    old_testcases: list[dict],
    regeneration_plan: dict,
    incremental_scenarios: list[dict],
) -> list[dict]:
    if isinstance(generated, dict):
        testcases = generated.get("testcases") or generated.get("test_cases") or []
    elif isinstance(generated, list):
        testcases = generated
    else:
        testcases = []

    next_testcase_id = _next_testcase_id_factory(old_testcases)
    scenario_by_id = {
        _scenario_id(scenario): scenario
        for scenario in incremental_scenarios or []
        if isinstance(scenario, dict) and _scenario_id(scenario)
    }
    impacted_by_scenario = {
        scenario_id: _testcases_for_scenarios(old_testcases, {scenario_id})
        for scenario_id in scenario_by_id
    }
    normalized = []

    for item in testcases or []:
        if not isinstance(item, dict):
            continue

        testcase = dict(item)
        scenario_id = _testcase_scenario_id(testcase)

        if not scenario_id or scenario_id not in scenario_by_id:
            continue

        scenario = scenario_by_id[scenario_id]
        related_requirement_ids = _unique(
            _as_list(testcase.get("related_requirement_ids"))
            + _as_list(testcase.get("requirement_ids"))
            + _related_requirement_ids(scenario)
        )
        change_status = _clean(testcase.get("change_status"))

        if change_status not in {"New", "Updated"}:
            change_status = "New" if scenario.get("change_status") == "New" else "Updated"

        previous_testcase_id = _clean(testcase.get("previous_testcase_id"))
        if change_status == "Updated" and not previous_testcase_id:
            old_matches = impacted_by_scenario.get(scenario_id, [])
            if old_matches:
                previous_testcase_id = _testcase_id(old_matches[0])

        testcase_id = _clean(testcase.get("testcase_id"))
        if not testcase_id or testcase_id == previous_testcase_id:
            testcase_id = next_testcase_id()

        source_refs = _unique(
            _as_list(testcase.get("source_refs"))
            + _as_list(scenario.get("source_refs"))
        )
        related_change_ids = _unique(
            _as_list(testcase.get("related_change_ids"))
            + _as_list(scenario.get("related_change_ids"))
        )
        expected_result = (
            testcase.get("expected_result")
            or testcase.get("expected")
            or testcase.get("expected_results")
            or ""
        )

        if isinstance(expected_result, list):
            expected_result = "\n".join(str(item) for item in expected_result)

        testcase["testcase_id"] = testcase_id
        testcase["scenario_id"] = scenario_id
        testcase["related_scenario_id"] = scenario_id
        testcase["related_requirement_ids"] = related_requirement_ids
        testcase["source_refs"] = source_refs
        testcase["change_status"] = change_status
        testcase["previous_testcase_id"] = previous_testcase_id
        testcase["related_change_ids"] = related_change_ids
        testcase["source_snapshot_version"] = regeneration_plan.get("source_snapshot_version")
        testcase["preconditions"] = _normalize_list_field(testcase.get("preconditions"))
        testcase["steps"] = _normalize_list_field(
            testcase.get("steps") or testcase.get("test_steps")
        )
        testcase["test_steps"] = testcase["steps"]
        testcase["expected_result"] = expected_result
        testcase["expected_results"] = _normalize_list_field(expected_result)
        testcase["traceability"] = ", ".join(related_requirement_ids)
        normalized.append(testcase)

    return classify_testcases_automation(normalized)


def regenerate_impacted_testcases(
    ticket_id: str,
    regeneration_plan: dict,
    incremental_scenarios: list[dict],
    ai_mode: str | None,
    source_channel: str | None = None,
) -> list[dict]:
    check_regeneration_safety(regeneration_plan)

    impacted_scenarios = _impacted_scenarios(incremental_scenarios)
    if not impacted_scenarios:
        return []

    old_testcases = load_latest_testcases(ticket_id)
    impacted_scenario_ids = {
        _scenario_id(scenario)
        for scenario in impacted_scenarios
        if _scenario_id(scenario)
    }
    old_impacted_testcases = _testcases_for_scenarios(old_testcases, impacted_scenario_ids)
    prompt = _testcase_prompt(
        ticket_id=ticket_id,
        regeneration_plan=regeneration_plan,
        incremental_scenarios=impacted_scenarios,
        old_impacted_testcases=old_impacted_testcases,
    )
    version = _next_testcase_version(ticket_id)
    raw_path = _logs_dir(ticket_id) / f"incremental_testcases_v{version}_raw.txt"

    try:
        content = call_text_llm(
            task_type=TASK_TESTCASE_GENERATION,
            prompt=prompt,
            ai_mode=ai_mode,
            source_channel=source_channel,
            format="json",
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as error:
        raise RuntimeError(f"Incremental test case generation failed: {error}") from error

    raw_response_path = _write_text(raw_path, content)

    try:
        _assert_json_candidate(content, raw_response_path)
        parsed = parse_json(content, label="incremental test case generation response")
    except Exception as error:
        parse_error_path = _write_text(
            _logs_dir(ticket_id) / f"incremental_testcases_v{version}_parse_error.txt",
            (
                "Incremental test case generation parse failure.\n"
                f"Error: {error}\n"
                f"Raw response path: {raw_response_path}\n"
            ),
        )
        raise RuntimeError(
            "Incremental test case generation response failed to parse JSON. "
            f"Check raw response at {raw_response_path} and parse error at {parse_error_path}."
        ) from error

    return _normalize_generated_testcases(
        parsed,
        old_testcases=old_testcases,
        regeneration_plan=regeneration_plan,
        incremental_scenarios=impacted_scenarios,
    )


def _deprecated_scenario_ids(regeneration_plan: dict) -> set[str]:
    return set(regeneration_plan.get("deprecated_candidate_scenario_ids", []) or [])


def merge_testcases(
    old_testcases: list[dict],
    new_testcases: list[dict],
    regeneration_plan: dict,
) -> list[dict]:
    impacted_testcase_ids = set(regeneration_plan.get("impacted_testcase_ids", []) or [])
    impacted_scenario_ids = set(regeneration_plan.get("impacted_scenario_ids", []) or [])
    deprecated_testcase_ids = set(
        regeneration_plan.get("deprecated_candidate_testcase_ids", []) or []
    )
    deprecated_scenario_ids = _deprecated_scenario_ids(regeneration_plan)
    replaced_ids = {
        _clean(testcase.get("previous_testcase_id"))
        for testcase in new_testcases or []
        if isinstance(testcase, dict) and testcase.get("previous_testcase_id")
    }
    merged = []

    for old in old_testcases or []:
        if not isinstance(old, dict):
            continue

        item = dict(old)
        testcase_id = _testcase_id(item)
        scenario_id = _testcase_scenario_id(item)

        if testcase_id in deprecated_testcase_ids or scenario_id in deprecated_scenario_ids:
            item["change_status"] = "DeprecatedCandidate"
        elif testcase_id in replaced_ids:
            item["change_status"] = "Replaced"
        elif testcase_id in impacted_testcase_ids or scenario_id in impacted_scenario_ids:
            item["change_status"] = "Replaced"
        else:
            item["change_status"] = "Unchanged"

        if scenario_id:
            item.setdefault("related_scenario_id", scenario_id)
        item.setdefault(
            "source_snapshot_version",
            regeneration_plan.get("source_snapshot_version"),
        )
        merged.append(item)

    existing_ids = {_testcase_id(item) for item in merged if isinstance(item, dict)}
    next_testcase_id = _next_testcase_id_factory(merged)

    for testcase in new_testcases or []:
        if not isinstance(testcase, dict):
            continue

        item = dict(testcase)
        testcase_id = _testcase_id(item)

        if not testcase_id or testcase_id in existing_ids:
            testcase_id = next_testcase_id()
            item["testcase_id"] = testcase_id

        scenario_id = _testcase_scenario_id(item)
        if scenario_id:
            item["scenario_id"] = scenario_id
            item["related_scenario_id"] = scenario_id

        existing_ids.add(testcase_id)
        merged.append(item)

    return classify_testcases_automation(merged)


def _testcase_merge_report(
    ticket_id: str,
    version: int,
    old_testcases: list[dict],
    new_testcases: list[dict],
    merged_testcases: list[dict],
    regeneration_plan: dict,
) -> dict:
    counts: dict[str, int] = {}
    for testcase in merged_testcases:
        status = testcase.get("change_status", "Unchanged")
        counts[status] = counts.get(status, 0) + 1

    return {
        "ticket_id": ticket_id,
        "version": version,
        "created_at": _utc_now(),
        "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
        "change_report_version": regeneration_plan.get("change_report_version"),
        "regeneration_plan_version": regeneration_plan.get("plan_version"),
        "old_testcase_count": len(old_testcases or []),
        "new_testcase_count": len(new_testcases or []),
        "merged_testcase_count": len(merged_testcases or []),
        "change_status_counts": counts,
        "impacted_requirement_ids": regeneration_plan.get("impacted_requirement_ids", []),
        "impacted_scenario_ids": regeneration_plan.get("impacted_scenario_ids", []),
        "impacted_testcase_ids": regeneration_plan.get("impacted_testcase_ids", []),
        "new_testcase_ids": [
            testcase.get("testcase_id")
            for testcase in new_testcases
            if isinstance(testcase, dict) and testcase.get("testcase_id")
        ],
        "replaced_testcase_ids": [
            testcase.get("previous_testcase_id")
            for testcase in new_testcases
            if isinstance(testcase, dict) and testcase.get("previous_testcase_id")
        ],
        "deprecated_candidate_testcase_ids": [
            testcase.get("testcase_id")
            for testcase in merged_testcases
            if isinstance(testcase, dict)
            and testcase.get("change_status") == "DeprecatedCandidate"
            and testcase.get("testcase_id")
        ],
    }


def save_incremental_testcase_version(
    ticket_id: str,
    merged_testcases: list[dict],
    report: dict,
) -> dict:
    version = int(report.get("version") or _next_testcase_version(ticket_id))
    report["version"] = version

    testcases_path = _write_json(
        _generated_dir(ticket_id) / f"incremental_testcases_v{version}.json",
        merged_testcases,
    )
    latest_path = _write_json(
        _generated_dir(ticket_id) / "latest_testcases.json",
        merged_testcases,
    )
    report_path = _write_json(
        _analysis_dir(ticket_id) / f"incremental_testcase_merge_report_v{version}.json",
        report,
    )

    return {
        "version": version,
        "testcases_path": testcases_path,
        "latest_testcases_path": latest_path,
        "merge_report_path": report_path,
        "new_testcase_count": report.get("new_testcase_count", 0),
        "merged_testcase_count": report.get("merged_testcase_count", 0),
        "change_status_counts": report.get("change_status_counts", {}),
    }


def run_incremental_testcase_generation(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> dict:
    regeneration_plan = load_latest_regeneration_plan(ticket_id)
    if not regeneration_plan:
        raise ValueError("No regeneration plan found. Build regeneration plan first.")

    incremental_scenarios = _latest_incremental_scenarios(ticket_id)
    if not incremental_scenarios:
        raise ValueError("No incremental scenarios found. Generate impacted scenarios first.")

    old_testcases = load_latest_testcases(ticket_id)
    new_testcases = regenerate_impacted_testcases(
        ticket_id=ticket_id,
        regeneration_plan=regeneration_plan,
        incremental_scenarios=incremental_scenarios,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )
    merged_testcases = merge_testcases(
        old_testcases=old_testcases,
        new_testcases=new_testcases,
        regeneration_plan=regeneration_plan,
    )
    version = _next_testcase_version(ticket_id)
    report = _testcase_merge_report(
        ticket_id=ticket_id,
        version=version,
        old_testcases=old_testcases,
        new_testcases=new_testcases,
        merged_testcases=merged_testcases,
        regeneration_plan=regeneration_plan,
    )

    return save_incremental_testcase_version(
        ticket_id=ticket_id,
        merged_testcases=merged_testcases,
        report=report,
    )
