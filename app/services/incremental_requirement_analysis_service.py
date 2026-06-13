import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.impact_mapping_service import load_latest_regeneration_plan
from app.services.jira_delta_service import load_latest_change_impact_report
from app.services.llm_router_service import (
    AI_MODE_NO_LLM,
    TASK_REQUIREMENT_ANALYSIS,
    call_text_llm,
)
from app.services.portal_ai_mode_service import get_current_portal_ai_mode
from app.utils.llm_json import parse_json


REQUIREMENTS_ROOT = Path("requirements")
LLM_REQUIRED_MESSAGE = (
    "This action requires LLM. Select TEST_LOCAL_ONLY or PRODUCTION_HYBRID."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _root(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id


def _analysis_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "analysis"


def _logs_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "logs"


def _read_text(path: Path, limit: int | None = None) -> str:
    if not path.exists() or not path.is_file():
        return ""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:limit] if limit else text


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


def _current_ai_mode() -> str | None:
    portal_ai_mode = get_current_portal_ai_mode()
    if portal_ai_mode:
        return portal_ai_mode.get("ai_mode")

    return None


def _next_incremental_version(ticket_id: str) -> int:
    max_version = 0
    analysis_dir = _analysis_dir(ticket_id)

    if analysis_dir.exists():
        for path in analysis_dir.glob("incremental_requirement_analysis_v*.json"):
            match = re.match(r"incremental_requirement_analysis_v(\d+)\.json$", path.name)
            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def _load_latest_jira_snapshot(ticket_id: str) -> dict:
    return _read_json(_root(ticket_id) / "snapshots" / "latest_jira_snapshot.json", {}) or {}


def _load_jira_payloads(ticket_id: str) -> list[dict]:
    jira_dir = _root(ticket_id) / "source" / "jira"
    payloads = []

    if jira_dir.exists():
        for path in sorted(jira_dir.glob("*_raw.json")):
            payload = _read_json(path, {})
            if isinstance(payload, dict) and payload:
                payloads.append(payload)

    payloads.sort(
        key=lambda item: (
            0 if _clean(item.get("key")).upper() == ticket_id.upper() else 1,
            _clean(item.get("key")),
        )
    )
    return payloads


def _issue_fields(issue: dict) -> dict:
    return issue.get("fields", {}) if isinstance(issue, dict) else {}


def _comments(issue: dict) -> list[dict]:
    comment_field = _issue_fields(issue).get("comment")
    if isinstance(comment_field, dict):
        comments = comment_field.get("comments") or []
    elif isinstance(comment_field, list):
        comments = comment_field
    else:
        comments = []

    return [item for item in comments if isinstance(item, dict)]


def _find_comment(payloads: list[dict], comment_id: str) -> dict:
    for issue in payloads:
        for comment in _comments(issue):
            if _clean(comment.get("id")) == comment_id:
                return {
                    "issue_key": _clean(issue.get("key")),
                    "comment_id": comment_id,
                    "author": (
                        (comment.get("author") or {}).get("displayName")
                        if isinstance(comment.get("author"), dict)
                        else ""
                    ),
                    "created": _clean(comment.get("created")),
                    "updated": _clean(comment.get("updated")),
                    "body": _clean(comment.get("body")),
                }

    return {}


def _find_subtask(payloads: list[dict], subtask_key: str) -> dict:
    for issue in payloads:
        if _clean(issue.get("key")).upper() == subtask_key.upper():
            fields = _issue_fields(issue)
            return {
                "subtask_key": subtask_key,
                "summary": _clean(fields.get("summary")),
                "description": _clean(fields.get("description")),
                "status": _clean((fields.get("status") or {}).get("name"))
                if isinstance(fields.get("status"), dict)
                else _clean(fields.get("status")),
                "updated": _clean(fields.get("updated")),
            }

    return {}


def _description_context(ticket_id: str) -> dict:
    description = _read_text(_root(ticket_id) / "source" / "description.md", limit=8000)

    if not description:
        description = _read_text(_root(ticket_id) / "source" / "jira_requirement.md", limit=8000)

    return {
        "context_kind": "jira_description",
        "text": description,
        "note": "Granular changed section was not available; using bounded stored description context.",
    }


def _attachment_context(ticket_id: str, source_id: str) -> dict:
    extracted_root = _root(ticket_id) / "source" / "extracted"
    normalized_source = source_id.replace("\\", "/").lower()
    matches = []

    if extracted_root.exists():
        for path in sorted(extracted_root.rglob("*.md")):
            path_text = str(path).replace("\\", "/").lower()
            if normalized_source in path_text or Path(normalized_source).stem in path.stem.lower():
                matches.append(path)

    texts = []
    for path in matches[:3]:
        content = _read_text(path, limit=6000)
        if content:
            texts.append({"path": str(path), "text": content})

    return {
        "context_kind": "jira_attachment",
        "attachments": texts,
    }


def _figma_screen_context(ticket_id: str, change: dict) -> dict:
    image_path = Path(_clean(change.get("image_path")))
    candidates = []

    if image_path.exists():
        candidates.append(image_path.parent)

    screen_node_id = _clean(change.get("screen_node_id"))
    snapshot = _load_latest_jira_snapshot(ticket_id)
    for item in snapshot.get("figma_screen_inventory", []) or []:
        if not isinstance(item, dict):
            continue
        if screen_node_id and _clean(item.get("screen_node_id")) == screen_node_id:
            candidates.append(Path(_clean(item.get("screen_path"))))

    screen_dir = next((path for path in candidates if path.exists()), None)
    if not screen_dir:
        return {"context_kind": "figma_screen", "text": "", "screen_path": ""}

    screen_context = _read_text(screen_dir / "screen_context.md", limit=7000)
    vision_analysis = _read_text(screen_dir / "vision_analysis.md", limit=7000)

    return {
        "context_kind": "figma_screen",
        "screen_path": str(screen_dir),
        "screen_name": _clean(change.get("screen_name")),
        "section_name": _clean(change.get("section_name")),
        "image_path": _clean(change.get("image_path")),
        "screen_context": screen_context,
        "vision_analysis": vision_analysis,
        "text": "\n\n".join(
            item for item in [screen_context, vision_analysis] if item.strip()
        ),
    }


def _change_by_id(change_report: dict) -> dict[str, dict]:
    return {
        _clean(change.get("change_id")): change
        for change in change_report.get("changes", []) or []
        if isinstance(change, dict) and change.get("change_id")
    }


def extract_changed_source_context(ticket_id: str, regeneration_plan: dict) -> list[dict]:
    change_report = load_latest_change_impact_report(ticket_id)
    changes = _change_by_id(change_report)
    payloads = _load_jira_payloads(ticket_id)
    contexts = []

    for source_ref in regeneration_plan.get("changed_source_refs", []) or []:
        if not isinstance(source_ref, dict):
            continue

        change_id = _clean(source_ref.get("change_id"))
        change = changes.get(change_id, source_ref)
        change_type = _clean(change.get("change_type"))
        source_type = _clean(change.get("source_type"))
        source_id = _clean(change.get("source_id"))
        context: dict[str, Any] = {}

        if source_type == "field" and source_id == "description":
            context = _description_context(ticket_id)
        elif source_type == "comment" and change_type in {"comment_added", "comment_modified"}:
            context = {
                "context_kind": "jira_comment",
                **_find_comment(payloads, source_id),
            }
        elif source_type == "subtask" and change_type in {"subtask_added", "subtask_modified"}:
            context = {
                "context_kind": "jira_subtask",
                **_find_subtask(payloads, source_id),
            }
        elif source_type == "attachment" and change_type in {"attachment_added", "attachment_modified"}:
            context = _attachment_context(ticket_id, source_id)
        elif source_type == "figma_screen" and change_type in {
            "figma_screen_added",
            "figma_screen_node_modified",
            "figma_screen_context_modified",
            "figma_screen_image_changed",
            "figma_vision_analysis_changed",
        }:
            context = _figma_screen_context(ticket_id, change)

        if not context:
            continue

        contexts.append(
            {
                "change_id": change_id,
                "change_type": change_type,
                "source_type": source_type,
                "source_id": source_id,
                "mapped_requirement_ids": source_ref.get("mapped_requirement_ids", []),
                "recommended_action": change.get("recommended_action", ""),
                "context": context,
            }
        )

    return contexts


def _incremental_prompt(ticket_id: str, changed_sources: list[dict], regeneration_plan: dict) -> str:
    return f"""
You are analyzing only changed source entities for an incremental QA requirement workflow.

Return STRICT JSON object only. No markdown. No prose outside JSON.

JSON schema:
{{
  "requirement_items": [
    {{
      "requirement_id": "REQ-NEW-001 or existing mapped requirement id",
      "title": "",
      "description": "",
      "type": "Functional | NonFunctional | UI | ClarificationNeeded | Other",
      "priority": "High | Medium | Low",
      "change_status": "New | Updated | Unchanged | DeprecatedCandidate",
      "source_refs": ["change/source reference"],
      "source_snapshot_version": {json.dumps(regeneration_plan.get("source_snapshot_version"))},
      "related_change_ids": ["CHG-001"]
    }}
  ],
  "clarification_questions": [
    {{
      "question_id": "IQ-001",
      "question": "",
      "related_requirement_ids": ["REQ-NEW-001"],
      "related_change_ids": ["CHG-001"],
      "priority": "High | Medium | Low",
      "blocking": true
    }}
  ]
}}

Rules:
- Analyze ONLY the changed source entities provided below.
- Do not infer requirements from unchanged Jira ticket content.
- If a changed source maps to existing requirement IDs, use change_status "Updated".
- If a changed source has no mapped requirement IDs, create new requirement_id values using REQ-INC-001, REQ-INC-002, ...
- If a source is ambiguous, create a clarification question instead of inventing details.
- Every requirement item must include change_status, source_refs, source_snapshot_version, and related_change_ids.
- Use the exact related change IDs from the input.

Ticket ID: {ticket_id}

Regeneration plan summary:
{json.dumps({
    "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
    "change_report_version": regeneration_plan.get("change_report_version"),
    "impact_confidence": regeneration_plan.get("impact_confidence"),
    "impacted_requirement_ids": regeneration_plan.get("impacted_requirement_ids", []),
}, ensure_ascii=False, indent=2)}

Changed sources:
{json.dumps(changed_sources, ensure_ascii=False, indent=2)}
""".strip()


def _assert_json_candidate(content: str, raw_path: str) -> None:
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Incremental requirement analysis returned an empty response.")

    lowered = content.strip().lower()
    if (
        lowered.startswith("[skipped]")
        or lowered.startswith("[error]")
        or "provider blocked" in lowered
        or "requires llm" in lowered
    ):
        raise RuntimeError(
            "Incremental requirement analysis did not receive a valid LLM JSON response."
        )

    stripped = content.strip()
    if stripped[0] not in "{[":
        raise RuntimeError(
            "Incremental requirement analysis returned non-JSON text. "
            f"Check raw response at {raw_path}."
        )


def _normalize_incremental_item(
    item: dict,
    index: int,
    regeneration_plan: dict,
) -> dict:
    normalized = dict(item)
    requirement_id = _clean(
        normalized.get("requirement_id")
        or normalized.get("id")
        or f"REQ-INC-{index:03d}"
    )
    change_status = _clean(normalized.get("change_status")) or "New"

    if change_status not in {"New", "Updated", "Unchanged", "DeprecatedCandidate"}:
        change_status = "Updated"

    normalized["requirement_id"] = requirement_id
    normalized["change_status"] = change_status
    normalized["source_refs"] = _unique(_as_list(normalized.get("source_refs")))
    normalized["source_snapshot_version"] = regeneration_plan.get("source_snapshot_version")
    normalized["related_change_ids"] = _unique(_as_list(normalized.get("related_change_ids")))
    return normalized


def analyze_changed_sources(
    ticket_id: str,
    changed_sources: list[dict],
    ai_mode: str | None,
) -> dict:
    effective_ai_mode = (ai_mode or _current_ai_mode() or "").strip().upper()

    if effective_ai_mode == AI_MODE_NO_LLM:
        raise RuntimeError(LLM_REQUIRED_MESSAGE)

    regeneration_plan = load_latest_regeneration_plan(ticket_id)
    if not regeneration_plan:
        raise ValueError("No regeneration plan found. Build regeneration plan first.")

    if not changed_sources:
        return {
            "requirement_items": [],
            "clarification_questions": [],
            "raw_response_path": "",
            "parse_error_path": "",
        }

    prompt = _incremental_prompt(ticket_id, changed_sources, regeneration_plan)
    version = _next_incremental_version(ticket_id)
    raw_path = _logs_dir(ticket_id) / f"incremental_requirement_analysis_v{version}_raw.txt"

    try:
        content = call_text_llm(
            task_type=TASK_REQUIREMENT_ANALYSIS,
            prompt=prompt,
            ai_mode=effective_ai_mode,
        )
    except Exception as error:
        if LLM_REQUIRED_MESSAGE in str(error):
            raise RuntimeError(LLM_REQUIRED_MESSAGE) from error

        raise RuntimeError(f"Incremental requirement analysis failed: {error}") from error

    raw_response_path = _write_text(raw_path, content)

    try:
        _assert_json_candidate(content, raw_response_path)
        parsed = parse_json(content, label="incremental requirement analysis response")
    except Exception as error:
        parse_error_path = _write_text(
            _logs_dir(ticket_id) / f"incremental_requirement_analysis_v{version}_parse_error.txt",
            (
                "Incremental requirement analysis parse failure.\n"
                f"Error: {error}\n"
                f"Raw response path: {raw_response_path}\n"
            ),
        )
        raise RuntimeError(
            "Incremental requirement analysis response failed to parse JSON. "
            f"Check raw response at {raw_response_path} and parse error at {parse_error_path}."
        ) from error

    if isinstance(parsed, list):
        parsed = {"requirement_items": parsed, "clarification_questions": []}

    if not isinstance(parsed, dict):
        raise RuntimeError("Incremental requirement analysis JSON must be an object.")

    items = parsed.get("requirement_items", [])
    if not isinstance(items, list):
        items = []

    normalized_items = [
        _normalize_incremental_item(item, index, regeneration_plan)
        for index, item in enumerate(items, start=1)
        if isinstance(item, dict)
    ]
    clarifications = parsed.get("clarification_questions", [])
    if not isinstance(clarifications, list):
        clarifications = []

    return {
        "requirement_items": normalized_items,
        "clarification_questions": clarifications,
        "raw_response_path": raw_response_path,
        "parse_error_path": "",
    }


def _load_old_requirement_items(ticket_id: str) -> list[dict]:
    items = _read_json(_analysis_dir(ticket_id) / "requirement_items.json", [])

    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict)]

    analysis = _read_json(_analysis_dir(ticket_id) / "requirement_analysis.json", {}) or {}
    items = (
        analysis.get("requirement_items")
        or analysis.get("requirements")
        or analysis.get("items")
        or []
    )

    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def merge_requirement_items(
    old_items: list[dict],
    incremental_items: list[dict],
    regeneration_plan: dict,
) -> list[dict]:
    impacted = set(regeneration_plan.get("impacted_requirement_ids", []) or [])
    deprecated = set(regeneration_plan.get("deprecated_candidate_testcase_ids", []) or [])
    merged: dict[str, dict] = {}

    for index, item in enumerate(old_items or [], start=1):
        if not isinstance(item, dict):
            continue

        requirement_id = _clean(
            item.get("requirement_id")
            or item.get("id")
            or item.get("item_id")
            or f"REQ-{index:03d}"
        )
        merged_item = dict(item)
        merged_item["requirement_id"] = requirement_id
        merged_item.setdefault(
            "change_status",
            "Updated" if requirement_id in impacted else "Unchanged",
        )
        if requirement_id in deprecated:
            merged_item["change_status"] = "DeprecatedCandidate"
        merged.setdefault(requirement_id, merged_item)

    for item in incremental_items or []:
        if not isinstance(item, dict):
            continue

        requirement_id = _clean(item.get("requirement_id"))
        if not requirement_id:
            continue

        existing = merged.get(requirement_id, {})
        merged[requirement_id] = {
            **existing,
            **item,
            "requirement_id": requirement_id,
        }

    return list(merged.values())


def save_incremental_requirement_analysis(
    ticket_id: str,
    incremental_result: dict,
    changed_sources: list[dict],
    merged_items: list[dict],
    regeneration_plan: dict,
) -> dict:
    version = _next_incremental_version(ticket_id)
    analysis = {
        "ticket_id": ticket_id,
        "version": version,
        "created_at": _utc_now(),
        "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
        "change_report_version": regeneration_plan.get("change_report_version"),
        "regeneration_plan_version": regeneration_plan.get("plan_version"),
        "changed_sources": changed_sources,
        "requirement_items": incremental_result.get("requirement_items", []),
        "merged_requirement_items_preview": merged_items,
        "raw_response_path": incremental_result.get("raw_response_path", ""),
    }

    items_path = _write_json(
        _analysis_dir(ticket_id) / f"incremental_requirement_items_v{version}.json",
        incremental_result.get("requirement_items", []),
    )
    analysis_path = _write_json(
        _analysis_dir(ticket_id) / f"incremental_requirement_analysis_v{version}.json",
        analysis,
    )
    clarifications = incremental_result.get("clarification_questions", [])
    clarifications_path = ""

    if clarifications:
        clarifications_path = _write_json(
            _analysis_dir(ticket_id) / f"incremental_clarifications_v{version}.json",
            {"clarification_questions": clarifications},
        )

    return {
        "version": version,
        "items_path": items_path,
        "analysis_path": analysis_path,
        "clarifications_path": clarifications_path,
    }


def run_incremental_requirement_analysis(
    ticket_id: str,
    ai_mode: str | None = None,
) -> dict:
    regeneration_plan = load_latest_regeneration_plan(ticket_id)
    if not regeneration_plan:
        raise ValueError("No regeneration plan found. Build regeneration plan first.")

    changed_sources = extract_changed_source_context(ticket_id, regeneration_plan)
    incremental_result = analyze_changed_sources(ticket_id, changed_sources, ai_mode)
    old_items = _load_old_requirement_items(ticket_id)
    merged_items = merge_requirement_items(
        old_items,
        incremental_result.get("requirement_items", []),
        regeneration_plan,
    )
    save_result = save_incremental_requirement_analysis(
        ticket_id,
        incremental_result,
        changed_sources,
        merged_items,
        regeneration_plan,
    )

    return {
        **save_result,
        "ticket_id": ticket_id,
        "changed_source_count": len(changed_sources),
        "incremental_requirement_count": len(incremental_result.get("requirement_items", [])),
        "incremental_clarification_count": len(
            incremental_result.get("clarification_questions", [])
        ),
        "source_snapshot_version": regeneration_plan.get("source_snapshot_version"),
    }
