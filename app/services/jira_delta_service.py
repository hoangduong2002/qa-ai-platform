import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

REQUIREMENTS_ROOT = Path("requirements")

ACTION_NO_CHANGE = "NO_CHANGE"
ACTION_ANALYZE_NEW_SOURCE_ONLY = "ANALYZE_NEW_SOURCE_ONLY"
ACTION_PARTIAL_REGENERATE_RECOMMENDED = "PARTIAL_REGENERATE_RECOMMENDED"
ACTION_FULL_REGENERATE_RECOMMENDED = "FULL_REGENERATE_RECOMMENDED"
ACTION_MANUAL_REVIEW_RECOMMENDED = "MANUAL_REVIEW_RECOMMENDED"
ACTION_REEXPORT_FRAME = "REEXPORT_FRAME"
ACTION_RERUN_VISION_ONLY = "RERUN_VISION_ONLY"
ACTION_UPDATE_COMPACT_CONTEXT = "UPDATE_COMPACT_CONTEXT"
ACTION_PARTIAL_REGENERATE_UI_TESTS = "PARTIAL_REGENERATE_UI_TESTS"

CHANGE_ACTIONS = {
    "summary_modified": ACTION_ANALYZE_NEW_SOURCE_ONLY,
    "description_modified": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "acceptance_criteria_modified": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "comment_added": ACTION_ANALYZE_NEW_SOURCE_ONLY,
    "comment_modified": ACTION_ANALYZE_NEW_SOURCE_ONLY,
    "comment_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "subtask_added": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "subtask_modified": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "subtask_removed": ACTION_FULL_REGENERATE_RECOMMENDED,
    "attachment_added": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "attachment_modified": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "attachment_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "figma_link_added": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "figma_link_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "figma_link_modified": ACTION_PARTIAL_REGENERATE_RECOMMENDED,
    "figma_page_added": ACTION_UPDATE_COMPACT_CONTEXT,
    "figma_page_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "figma_section_added": ACTION_UPDATE_COMPACT_CONTEXT,
    "figma_section_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "figma_screen_added": ACTION_PARTIAL_REGENERATE_UI_TESTS,
    "figma_screen_removed": ACTION_MANUAL_REVIEW_RECOMMENDED,
    "figma_screen_node_modified": ACTION_UPDATE_COMPACT_CONTEXT,
    "figma_screen_context_modified": ACTION_UPDATE_COMPACT_CONTEXT,
    "figma_screen_image_changed": ACTION_RERUN_VISION_ONLY,
    "figma_vision_analysis_changed": ACTION_UPDATE_COMPACT_CONTEXT,
}

ACTION_RANK = {
    ACTION_NO_CHANGE: 0,
    ACTION_ANALYZE_NEW_SOURCE_ONLY: 1,
    ACTION_PARTIAL_REGENERATE_RECOMMENDED: 2,
    ACTION_REEXPORT_FRAME: 2,
    ACTION_RERUN_VISION_ONLY: 2,
    ACTION_UPDATE_COMPACT_CONTEXT: 2,
    ACTION_PARTIAL_REGENERATE_UI_TESTS: 3,
    ACTION_FULL_REGENERATE_RECOMMENDED: 4,
    ACTION_MANUAL_REVIEW_RECOMMENDED: 5,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _requirement_root(ticket_id: str, source_root: str | Path | None = None) -> Path:
    if source_root is None:
        return REQUIREMENTS_ROOT / ticket_id

    root = Path(source_root)

    if root.name == "source" and (root / "jira").exists():
        return root.parent

    return root


def _snapshots_dir(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id / "snapshots"


def _snapshot_file(ticket_id: str, version: int) -> Path:
    return _snapshots_dir(ticket_id) / f"jira_snapshot_v{version}.json"


def _latest_snapshot_file(ticket_id: str) -> Path:
    return _snapshots_dir(ticket_id) / "latest_jira_snapshot.json"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8", errors="ignore")


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _to_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    return _canonical_json(value)


def _sha256_text(value: Any) -> str | None:
    text = _to_text(value)

    if not text:
        return None

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    hasher = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def _author_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    return (
        value.get("displayName")
        or value.get("name")
        or value.get("key")
        or ""
    )


def _fields(issue: dict) -> dict:
    return issue.get("fields", {}) if isinstance(issue, dict) else {}


def _issue_key(issue: dict) -> str:
    return str(issue.get("key") or "").strip()


def _issue_updated(issue: dict) -> str:
    return str(_fields(issue).get("updated") or "").strip()


def _issue_summary(issue: dict) -> str:
    return _to_text(_fields(issue).get("summary"))


def _issue_description(issue: dict) -> str:
    return _to_text(_fields(issue).get("description"))


def _issue_status(issue: dict) -> str:
    status = _fields(issue).get("status")
    if isinstance(status, dict):
        return str(status.get("name") or "").strip()

    return str(status or "").strip()


def _comment_items(issue: dict) -> list[dict]:
    comment_field = _fields(issue).get("comment")

    if isinstance(comment_field, dict):
        comments = comment_field.get("comments", []) or []
    elif isinstance(comment_field, list):
        comments = comment_field
    else:
        comments = []

    return [item for item in comments if isinstance(item, dict)]


def _attachment_items(issue: dict) -> list[dict]:
    attachments = _fields(issue).get("attachment", []) or []
    return [item for item in attachments if isinstance(item, dict)]


def _subtask_stub_items(issue: dict) -> list[dict]:
    subtasks = _fields(issue).get("subtasks", []) or []
    return [item for item in subtasks if isinstance(item, dict)]


def _find_acceptance_criteria(fields: dict) -> Any:
    for key, value in fields.items():
        normalized_key = str(key).lower().replace("_", " ")
        if "acceptance" in normalized_key and "criteria" in normalized_key:
            return value

    for key, value in fields.items():
        if isinstance(value, dict):
            name = str(value.get("name") or value.get("label") or "").lower()
            if "acceptance" in name and "criteria" in name:
                return value

    return None


def _load_issue_payloads(ticket_id: str, root: Path, jira_payload: dict) -> list[dict]:
    payloads: list[dict] = []

    if isinstance(jira_payload, dict) and jira_payload:
        payloads.append(jira_payload)

        included_issues = jira_payload.get("_included_issues")
        if isinstance(included_issues, list):
            payloads.extend(
                item
                for item in included_issues
                if isinstance(item, dict) and item
            )
            payloads.sort(
                key=lambda item: (
                    0 if _issue_key(item) == ticket_id else 1,
                    _issue_key(item),
                )
            )
            return payloads

    jira_dir = root / "source" / "jira"
    seen_keys = {_issue_key(item) for item in payloads if _issue_key(item)}

    if jira_dir.exists():
        for raw_file in sorted(jira_dir.glob("*_raw.json")):
            item = _read_json(raw_file, {})

            if not isinstance(item, dict) or not item:
                continue

            key = _issue_key(item)

            if key and key in seen_keys:
                continue

            payloads.append(item)

            if key:
                seen_keys.add(key)

    payloads.sort(key=lambda item: (0 if _issue_key(item) == ticket_id else 1, _issue_key(item)))
    return payloads


def _jira_source_paths(ticket_id: str, root: Path, normalized_requirement_text: str | None) -> dict:
    source_dir = root / "source"
    jira_dir = source_dir / "jira"
    raw_payloads = []

    if jira_dir.exists():
        raw_payloads = [
            str(path)
            for path in sorted(jira_dir.glob("*_raw.json"))
        ]

    normalized_path = root / "analysis" / "sanitized_requirement.md"

    return {
        "requirement_root": str(root),
        "jira_raw_payloads": raw_payloads,
        "jira_requirement_md": (
            str(source_dir / "jira_requirement.md")
            if (source_dir / "jira_requirement.md").exists()
            else ""
        ),
        "normalized_requirement": (
            str(normalized_path)
            if normalized_requirement_text is not None and normalized_path.exists()
            else ""
        ),
        "figma_links": (
            str(source_dir / "figma_links.json")
            if (source_dir / "figma_links.json").exists()
            else ""
        ),
        "attachments_root": (
            str(source_dir / "attachments")
            if (source_dir / "attachments").exists()
            else ""
        ),
    }


def _jira_updated_fallback(root: Path) -> str:
    ticket = _read_json(root / "ticket.json", {}) or {}
    metadata = _read_json(root / "metadata.json", {}) or {}

    return str(
        ticket.get("jira_updated")
        or ticket.get("source_refreshed_at")
        or ticket.get("updated_at")
        or metadata.get("source_refreshed_at")
        or metadata.get("source_loaded_at")
        or metadata.get("updated_at")
        or ""
    )


def _comments_inventory(payloads: list[dict]) -> list[dict]:
    inventory = []

    for issue in payloads:
        issue_key = _issue_key(issue)

        for index, comment in enumerate(_comment_items(issue), start=1):
            body = _to_text(comment.get("body"))
            comment_id = str(comment.get("id") or f"{issue_key}:{index}")

            inventory.append(
                {
                    "comment_id": comment_id,
                    "issue_key": issue_key,
                    "author": _author_name(comment.get("author")),
                    "created": str(comment.get("created") or ""),
                    "updated": str(comment.get("updated") or ""),
                    "body_hash": _sha256_text(body),
                    "body_preview": body.strip()[:200],
                }
            )

    return sorted(
        inventory,
        key=lambda item: (item.get("issue_key") or "", item.get("comment_id") or ""),
    )


def _subtasks_inventory(main_issue: dict, payloads: list[dict]) -> list[dict]:
    payload_by_key = {
        _issue_key(issue): issue
        for issue in payloads
        if _issue_key(issue)
    }
    subtask_keys = []

    for subtask in _subtask_stub_items(main_issue):
        key = str(subtask.get("key") or "").strip()
        if key:
            subtask_keys.append(key)

    for issue in payloads:
        key = _issue_key(issue)
        if key and key != _issue_key(main_issue) and key not in subtask_keys:
            subtask_keys.append(key)

    inventory = []

    for key in subtask_keys:
        issue = payload_by_key.get(key, {})
        stub = next(
            (
                item
                for item in _subtask_stub_items(main_issue)
                if str(item.get("key") or "").strip() == key
            ),
            {},
        )
        fields = _fields(issue) or _fields(stub)

        inventory.append(
            {
                "subtask_key": key,
                "summary_hash": _sha256_text(fields.get("summary")),
                "description_hash": _sha256_text(fields.get("description")),
                "status": _issue_status(issue) or _issue_status(stub),
                "updated": _issue_updated(issue) or str(fields.get("updated") or ""),
            }
        )

    return sorted(inventory, key=lambda item: item.get("subtask_key") or "")


def _attachment_local_path(root: Path, issue_key: str, filename: str) -> Path:
    return root / "source" / "attachments" / issue_key / filename


def _attachments_inventory(root: Path, payloads: list[dict]) -> list[dict]:
    inventory = []

    for issue in payloads:
        issue_key = _issue_key(issue)

        for attachment in _attachment_items(issue):
            filename = str(attachment.get("filename") or "")
            local_path = _attachment_local_path(root, issue_key, filename)

            inventory.append(
                {
                    "attachment_id": str(attachment.get("id") or ""),
                    "issue_key": issue_key,
                    "filename": filename,
                    "mime_type": str(
                        attachment.get("mimeType")
                        or attachment.get("mime_type")
                        or ""
                    ),
                    "size": attachment.get("size"),
                    "created": str(attachment.get("created") or ""),
                    "content_hash": _sha256_file(local_path),
                    "local_path": str(local_path) if local_path.exists() else "",
                }
            )

    return sorted(
        inventory,
        key=lambda item: (
            item.get("issue_key") or "",
            item.get("attachment_id") or "",
            item.get("filename") or "",
        ),
    )


def _normalize_figma_url(original_url: str, file_key: str, node_id: str) -> str:
    parsed = urlparse(original_url or "")
    query = parse_qs(parsed.query)
    normalized_query = {}

    if node_id:
        normalized_query["node-id"] = node_id.replace(":", "-")

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            urlencode(normalized_query, doseq=True),
            "",
        )
    ) or f"figma:{file_key}:{node_id}"


def _figma_record_from_url(original_url: str) -> dict | None:
    parsed = urlparse(original_url)
    parts = [part for part in parsed.path.split("/") if part]
    file_key = ""

    for index, part in enumerate(parts):
        if part in {"file", "design"} and index + 1 < len(parts):
            file_key = parts[index + 1]
            break

    query = parse_qs(parsed.query)
    node_id = (query.get("node-id") or [""])[0].replace("-", ":")

    if not file_key and not node_id:
        return None

    return {
        "original_url": original_url,
        "file_key": file_key,
        "node_ids": [node_id] if node_id else [],
    }


def _figma_records_from_payloads(payloads: list[dict]) -> list[dict]:
    records = []
    pattern = re.compile(r"https://(?:www\.)?figma\.com/[^\s)>\]\"']+")

    for issue in payloads:
        texts = [_issue_description(issue)]
        texts.extend(_to_text(comment.get("body")) for comment in _comment_items(issue))

        for text in texts:
            for match in pattern.findall(text or ""):
                record = _figma_record_from_url(match.rstrip(".,;"))

                if record:
                    records.append(record)

    return records


def _figma_links_inventory(root: Path, payloads: list[dict] | None = None) -> list[dict]:
    links_file = root / "source" / "figma_links.json"
    records = _read_json(links_file, []) or []

    if not isinstance(records, list):
        records = []

    records = list(records)
    records.extend(_figma_records_from_payloads(payloads or []))

    inventory = []
    seen = set()

    for record in records:
        if not isinstance(record, dict):
            continue

        original_url = str(record.get("original_url") or record.get("url") or "")
        file_key = str(record.get("file_key") or "")
        node_ids = record.get("node_ids") or record.get("node_id") or []

        if isinstance(node_ids, str):
            node_ids = [node_ids]

        if not isinstance(node_ids, list) or not node_ids:
            node_ids = [""]

        for node_id in node_ids:
            node_id = str(node_id or "")
            normalized_url = _normalize_figma_url(original_url, file_key, node_id)
            identity = (file_key, node_id, _sha256_text(normalized_url))

            if identity in seen:
                continue

            seen.add(identity)

            inventory.append(
                {
                    "original_url": original_url,
                    "file_key": file_key,
                    "node_id": node_id,
                    "page_id": str(record.get("page_id") or ""),
                    "normalized_url_hash": _sha256_text(normalized_url),
                }
            )

    return sorted(
        inventory,
        key=lambda item: (
            item.get("file_key") or "",
            item.get("node_id") or "",
            item.get("original_url") or "",
        ),
    )


def _safe_figma_id(value: str) -> str:
    return str(value or "").replace(":", "_")


def _figma_metadata_map(items: Any) -> dict[str, dict]:
    mapping = {}

    if not isinstance(items, list):
        return mapping

    for item in items:
        if not isinstance(item, dict):
            continue

        node_id = str(item.get("node_id") or item.get("id") or "").strip()

        if not node_id:
            continue

        mapping[node_id] = item
        mapping[_safe_figma_id(node_id)] = item

    return mapping


def _collect_figma_text_and_components(node: Any) -> tuple[list[str], list[str]]:
    texts = []
    components = []

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return

        node_type = str(value.get("type") or "").upper()
        name = str(value.get("name") or "").strip()

        if node_type == "TEXT":
            text = str(value.get("characters") or value.get("text") or "").strip()
            if text:
                texts.append(text)

        if node_type in {"COMPONENT", "COMPONENT_SET", "INSTANCE"}:
            component_id = str(
                value.get("componentId")
                or value.get("componentSetId")
                or ""
            ).strip()
            component_label = component_id or name

            if component_label:
                components.append(component_label)

        for child in value.get("children") or []:
            visit(child)

    visit(node)
    return texts, components


def _hash_sorted_values(values: list[str]) -> str | None:
    clean_values = sorted({value.strip() for value in values if value and value.strip()})

    if not clean_values:
        return None

    return _sha256_text(clean_values)


def _figma_screen_inventory(root: Path) -> list[dict]:
    figma_root = root / "source" / "figma"

    if not figma_root.exists():
        return []

    inventory = []

    for file_dir in sorted(path for path in figma_root.iterdir() if path.is_dir()):
        file_key = file_dir.name

        for page_dir in sorted(path for path in file_dir.iterdir() if path.is_dir()):
            page_metadata = _read_json(page_dir / "page_metadata.json", {}) or {}
            page_id = str(page_metadata.get("page_id") or page_dir.name)
            layers_by_id = _figma_metadata_map(_read_json(page_dir / "extracted_layers.json", []))
            screens_by_id = _figma_metadata_map(_read_json(page_dir / "extracted_screens.json", []))
            layers_root = page_dir / "layers"

            if not layers_root.exists():
                continue

            for section_dir in sorted(path for path in layers_root.iterdir() if path.is_dir()):
                section_data = layers_by_id.get(section_dir.name) or _read_json(
                    section_dir / "layer.json",
                    {},
                ) or {}
                section_id = str(
                    section_data.get("node_id")
                    or section_data.get("id")
                    or section_dir.name
                )
                section_name = str(section_data.get("name") or "")
                screens_root = section_dir / "screens"

                if not screens_root.exists():
                    continue

                for screen_dir in sorted(path for path in screens_root.iterdir() if path.is_dir()):
                    screen_node_path = screen_dir / "screen_node.json"
                    screen_context_path = screen_dir / "screen_context.md"
                    vision_analysis_path = screen_dir / "vision_analysis.md"
                    frame_image_path = screen_dir / "frame.png"
                    screen_node = _read_json(screen_node_path, {}) or {}
                    screen_data = screens_by_id.get(screen_dir.name) or screen_node or {}
                    screen_node_id = str(
                        screen_data.get("node_id")
                        or screen_data.get("id")
                        or screen_dir.name
                    )
                    screen_name = str(screen_data.get("name") or "")
                    texts, components = _collect_figma_text_and_components(screen_node)

                    inventory.append(
                        {
                            "file_key": file_key,
                            "page_id": page_id,
                            "section_id": section_id,
                            "section_name": section_name,
                            "screen_node_id": screen_node_id,
                            "screen_name": screen_name,
                            "screen_path": str(screen_dir),
                            "frame_image_path": (
                                str(frame_image_path) if frame_image_path.exists() else ""
                            ),
                            "image_hash": _sha256_file(frame_image_path),
                            "screen_node_hash": _sha256_file(screen_node_path),
                            "screen_context_hash": _sha256_text(_read_text(screen_context_path)),
                            "vision_analysis_hash": _sha256_text(_read_text(vision_analysis_path)),
                            "text_hash": _hash_sorted_values(texts),
                            "component_hash": _hash_sorted_values(components),
                        }
                    )

    return sorted(
        inventory,
        key=lambda item: (
            item.get("file_key") or "",
            item.get("page_id") or "",
            item.get("section_id") or "",
            item.get("screen_node_id") or "",
        ),
    )


def get_next_snapshot_version(ticket_id: str) -> int:
    snapshots_dir = _snapshots_dir(ticket_id)
    max_version = 0

    if snapshots_dir.exists():
        for path in snapshots_dir.glob("jira_snapshot_v*.json"):
            match = re.match(r"jira_snapshot_v(\d+)\.json$", path.name)

            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def build_jira_snapshot(
    ticket_id: str,
    jira_payload: dict,
    normalized_requirement_text: str | None = None,
    source_root: str | Path | None = None,
) -> dict:
    root = _requirement_root(ticket_id, source_root)
    main_issue = jira_payload if isinstance(jira_payload, dict) else {}
    payloads = _load_issue_payloads(ticket_id, root, main_issue)

    if not payloads:
        raise ValueError(f"No stored Jira payload found for {ticket_id}.")

    main_issue = payloads[0]
    main_fields = _fields(main_issue)
    comments = _comments_inventory(payloads)
    subtasks = _subtasks_inventory(main_issue, payloads)
    attachments = _attachments_inventory(root, payloads)
    figma_links = _figma_links_inventory(root, payloads)
    figma_screens = _figma_screen_inventory(root)
    acceptance_criteria = _find_acceptance_criteria(main_fields)
    summary = _issue_summary(main_issue)
    description = _issue_description(main_issue)
    source_paths = _jira_source_paths(ticket_id, root, normalized_requirement_text)
    figma_pages = {
        f"{item.get('file_key') or ''}:{item.get('page_id') or ''}"
        for item in figma_screens
    }
    figma_sections = {
        (
            f"{item.get('file_key') or ''}:"
            f"{item.get('page_id') or ''}:"
            f"{item.get('section_id') or ''}"
        )
        for item in figma_screens
    }

    return {
        "metadata": {
            "ticket_id": ticket_id,
            "snapshot_version": get_next_snapshot_version(ticket_id),
            "created_at": _utc_now(),
            "jira_updated": _issue_updated(main_issue) or _jira_updated_fallback(root),
            "source_paths": source_paths,
        },
        "field_hashes": {
            "summary_hash": _sha256_text(summary),
            "description_hash": _sha256_text(description),
            "acceptance_criteria_hash": _sha256_text(acceptance_criteria),
            "normalized_requirement_hash": _sha256_text(normalized_requirement_text),
            "comments_hash": _sha256_text(comments),
            "subtasks_hash": _sha256_text(subtasks),
            "attachments_hash": _sha256_text(attachments),
            "figma_hash": _sha256_text(
                {
                    "links": figma_links,
                    "screens": figma_screens,
                }
            ),
            "figma_screen_hash": _sha256_text(figma_screens),
        },
        "comments_inventory": comments,
        "subtasks_inventory": subtasks,
        "attachments_inventory": attachments,
        "figma_links_inventory": figma_links,
        "figma_screen_inventory": figma_screens,
        "raw_lengths": {
            "summary_chars": len(summary),
            "description_chars": len(description),
            "comments_count": len(comments),
            "subtasks_count": len(subtasks),
            "attachments_count": len(attachments),
            "figma_links_count": len(figma_links),
            "figma_pages_count": len(figma_pages),
            "figma_sections_count": len(figma_sections),
            "figma_screens_count": len(figma_screens),
        },
    }


def save_jira_snapshot(ticket_id: str, snapshot: dict) -> dict:
    metadata = snapshot.setdefault("metadata", {})
    version = int(metadata.get("snapshot_version") or get_next_snapshot_version(ticket_id))
    metadata["ticket_id"] = ticket_id
    metadata["snapshot_version"] = version

    versioned_file = _snapshot_file(ticket_id, version)
    latest_file = _latest_snapshot_file(ticket_id)

    _write_json(versioned_file, snapshot)
    _write_json(latest_file, snapshot)

    return {
        "ticket_id": ticket_id,
        "snapshot_version": version,
        "snapshot_path": str(versioned_file),
        "latest_snapshot_path": str(latest_file),
    }


def load_latest_jira_snapshot(ticket_id: str) -> dict | None:
    return _read_json(_latest_snapshot_file(ticket_id), None)


def load_stored_jira_payload(ticket_id: str, source_root: str | Path | None = None) -> dict:
    root = _requirement_root(ticket_id, source_root)
    ticket = _read_json(root / "ticket.json", {}) or {}
    jira_key = str(ticket.get("jira_key") or ticket_id).strip()
    jira_dir = root / "source" / "jira"
    candidates = []

    if jira_key:
        candidates.append(jira_dir / f"{jira_key}_raw.json")

    candidates.append(jira_dir / f"{ticket_id}_raw.json")

    if jira_dir.exists():
        candidates.extend(sorted(jira_dir.glob("*_raw.json")))

    seen = set()

    for path in candidates:
        if path in seen:
            continue

        seen.add(path)
        payload = _read_json(path, None)

        if isinstance(payload, dict) and payload:
            return payload

    raise ValueError(f"No stored Jira payload found for {ticket_id}.")


def build_and_save_latest_stored_jira_snapshot(ticket_id: str) -> dict:
    root = REQUIREMENTS_ROOT / ticket_id
    normalized_text = _read_text(root / "analysis" / "sanitized_requirement.md")
    payload = load_stored_jira_payload(ticket_id, root)
    snapshot = build_jira_snapshot(
        ticket_id=ticket_id,
        jira_payload=payload,
        normalized_requirement_text=normalized_text or None,
        source_root=root,
    )
    save_result = save_jira_snapshot(ticket_id, snapshot)

    return {
        **save_result,
        "jira_updated": snapshot.get("metadata", {}).get("jira_updated", ""),
        "field_hashes": snapshot.get("field_hashes", {}),
        "raw_lengths": snapshot.get("raw_lengths", {}),
    }


def _analysis_dir(ticket_id: str) -> Path:
    return REQUIREMENTS_ROOT / ticket_id / "analysis"


def _change_report_file(ticket_id: str, version: int, suffix: str) -> Path:
    return _analysis_dir(ticket_id) / f"change_impact_report_v{version}.{suffix}"


def _latest_change_report_file(ticket_id: str) -> Path:
    return _analysis_dir(ticket_id) / "latest_change_impact_report.json"


def _get_next_change_report_version(ticket_id: str) -> int:
    analysis_dir = _analysis_dir(ticket_id)
    max_version = 0

    if analysis_dir.exists():
        for path in analysis_dir.glob("change_impact_report_v*.json"):
            match = re.match(r"change_impact_report_v(\d+)\.json$", path.name)

            if match:
                max_version = max(max_version, int(match.group(1)))

    return max_version + 1


def _item_hash(item: dict, ignored_keys: set[str] | None = None) -> str | None:
    ignored_keys = ignored_keys or set()
    payload = {
        key: value
        for key, value in item.items()
        if key not in ignored_keys
    }
    return _sha256_text(payload)


def _field_change(
    change_type: str,
    source_id: str,
    old_hash: str | None,
    new_hash: str | None,
    summary: str,
) -> dict:
    return {
        "source_type": "field",
        "source_id": source_id,
        "change_type": change_type,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "summary": summary,
        "recommended_action": CHANGE_ACTIONS[change_type],
        "impact_confidence": "HIGH",
    }


def _inventory_map(items: list[dict], key_name: str) -> dict[str, dict]:
    result = {}

    for item in items or []:
        if not isinstance(item, dict):
            continue

        key = str(item.get(key_name) or "").strip()

        if key:
            result[key] = item

    return result


def _attachment_key(item: dict) -> str:
    attachment_id = str(item.get("attachment_id") or "").strip()

    if attachment_id:
        return attachment_id

    return f"{item.get('issue_key') or ''}:{item.get('filename') or ''}"


def _figma_key(item: dict) -> str:
    return (
        f"{item.get('file_key') or ''}:"
        f"{item.get('node_id') or ''}"
    )


def _figma_page_key(item: dict) -> str:
    return f"{item.get('file_key') or ''}:{item.get('page_id') or ''}"


def _figma_section_key(item: dict) -> str:
    return (
        f"{item.get('file_key') or ''}:"
        f"{item.get('page_id') or ''}:"
        f"{item.get('section_id') or ''}"
    )


def _figma_screen_key(item: dict) -> str:
    return (
        f"{item.get('file_key') or ''}:"
        f"{item.get('page_id') or ''}:"
        f"{item.get('screen_node_id') or ''}"
    )


def _map_by_key(items: list[dict], key_func) -> dict[str, dict]:
    result = {}

    for item in items or []:
        if not isinstance(item, dict):
            continue

        key = str(key_func(item)).strip()

        if key:
            result[key] = item

    return result


def _append_inventory_changes(
    changes: list[dict],
    *,
    source_type: str,
    old_items: dict[str, dict],
    new_items: dict[str, dict],
    add_type: str,
    modify_type: str,
    remove_type: str,
    hash_ignore_keys: set[str] | None = None,
) -> None:
    all_ids = sorted(set(old_items.keys()) | set(new_items.keys()))

    for source_id in all_ids:
        old_item = old_items.get(source_id)
        new_item = new_items.get(source_id)

        if old_item is None and new_item is not None:
            change_type = add_type
            old_hash = None
            new_hash = _item_hash(new_item, hash_ignore_keys)
            summary = f"{source_type} added: {source_id}"
        elif old_item is not None and new_item is None:
            change_type = remove_type
            old_hash = _item_hash(old_item, hash_ignore_keys)
            new_hash = None
            summary = f"{source_type} removed: {source_id}"
        else:
            old_hash = _item_hash(old_item or {}, hash_ignore_keys)
            new_hash = _item_hash(new_item or {}, hash_ignore_keys)

            if old_hash == new_hash:
                continue

            change_type = modify_type
            summary = f"{source_type} modified: {source_id}"

        changes.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "change_type": change_type,
                "old_hash": old_hash,
                "new_hash": new_hash,
                "summary": summary,
                "recommended_action": CHANGE_ACTIONS[change_type],
                "impact_confidence": "HIGH",
            }
        )


def _figma_scope_item(items: list[dict], key_func) -> dict[str, dict]:
    result = {}

    for item in items:
        key = key_func(item)

        if key and key not in result:
            result[key] = item

    return result


def _figma_screen_change(
    *,
    change_type: str,
    source_type: str,
    source_id: str,
    old_hash: str | None,
    new_hash: str | None,
    summary: str,
    item: dict | None,
    confidence: str = "HIGH",
) -> dict:
    item = item or {}

    return {
        "source_type": source_type,
        "source_id": source_id,
        "change_type": change_type,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "summary": summary,
        "recommended_action": CHANGE_ACTIONS[change_type],
        "impact_confidence": confidence,
        "file_key": item.get("file_key") or "",
        "page_id": item.get("page_id") or "",
        "section_id": item.get("section_id") or "",
        "section_name": item.get("section_name") or "",
        "screen_node_id": item.get("screen_node_id") or "",
        "screen_name": item.get("screen_name") or "",
        "image_path": item.get("frame_image_path") or "",
    }


def _append_figma_scope_changes(
    changes: list[dict],
    *,
    source_type: str,
    old_items: dict[str, dict],
    new_items: dict[str, dict],
    add_type: str,
    remove_type: str,
) -> None:
    all_ids = sorted(set(old_items.keys()) | set(new_items.keys()))

    for source_id in all_ids:
        old_item = old_items.get(source_id)
        new_item = new_items.get(source_id)

        if old_item is None and new_item is not None:
            changes.append(
                _figma_screen_change(
                    change_type=add_type,
                    source_type=source_type,
                    source_id=source_id,
                    old_hash=None,
                    new_hash=_item_hash(new_item),
                    summary=f"Figma {source_type} added: {source_id}",
                    item=new_item,
                    confidence="MEDIUM",
                )
            )
        elif old_item is not None and new_item is None:
            changes.append(
                _figma_screen_change(
                    change_type=remove_type,
                    source_type=source_type,
                    source_id=source_id,
                    old_hash=_item_hash(old_item),
                    new_hash=None,
                    summary=f"Figma {source_type} removed: {source_id}",
                    item=old_item,
                    confidence="MEDIUM",
                )
            )


def _screen_hash_for_node_change(item: dict) -> str | None:
    return _sha256_text(
        {
            "screen_node_hash": item.get("screen_node_hash"),
            "text_hash": item.get("text_hash"),
            "component_hash": item.get("component_hash"),
        }
    )


def _append_figma_screen_changes(
    changes: list[dict],
    old_screens: list[dict],
    new_screens: list[dict],
) -> None:
    old_screen_map = _map_by_key(old_screens, _figma_screen_key)
    new_screen_map = _map_by_key(new_screens, _figma_screen_key)

    _append_figma_scope_changes(
        changes,
        source_type="figma_page",
        old_items=_figma_scope_item(old_screens, _figma_page_key),
        new_items=_figma_scope_item(new_screens, _figma_page_key),
        add_type="figma_page_added",
        remove_type="figma_page_removed",
    )
    _append_figma_scope_changes(
        changes,
        source_type="figma_section",
        old_items=_figma_scope_item(old_screens, _figma_section_key),
        new_items=_figma_scope_item(new_screens, _figma_section_key),
        add_type="figma_section_added",
        remove_type="figma_section_removed",
    )

    for source_id in sorted(set(old_screen_map.keys()) | set(new_screen_map.keys())):
        old_item = old_screen_map.get(source_id)
        new_item = new_screen_map.get(source_id)
        display_item = new_item or old_item or {}
        screen_label = display_item.get("screen_name") or source_id
        section_label = display_item.get("section_name") or display_item.get("section_id") or ""

        if old_item is None and new_item is not None:
            changes.append(
                _figma_screen_change(
                    change_type="figma_screen_added",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=None,
                    new_hash=_item_hash(new_item),
                    summary=f"Figma screen added: {screen_label} in {section_label}.",
                    item=new_item,
                )
            )
            continue

        if old_item is not None and new_item is None:
            changes.append(
                _figma_screen_change(
                    change_type="figma_screen_removed",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=_item_hash(old_item),
                    new_hash=None,
                    summary=f"Figma screen removed: {screen_label} from {section_label}.",
                    item=old_item,
                )
            )
            continue

        if not old_item or not new_item:
            continue

        if old_item.get("image_hash") != new_item.get("image_hash"):
            changes.append(
                _figma_screen_change(
                    change_type="figma_screen_image_changed",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=old_item.get("image_hash"),
                    new_hash=new_item.get("image_hash"),
                    summary=f"Figma screen image changed: {screen_label} in {section_label}.",
                    item=new_item,
                )
            )

        if old_item.get("screen_context_hash") != new_item.get("screen_context_hash"):
            changes.append(
                _figma_screen_change(
                    change_type="figma_screen_context_modified",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=old_item.get("screen_context_hash"),
                    new_hash=new_item.get("screen_context_hash"),
                    summary=f"Figma screen context changed: {screen_label} in {section_label}.",
                    item=new_item,
                )
            )

        old_node_hash = _screen_hash_for_node_change(old_item)
        new_node_hash = _screen_hash_for_node_change(new_item)

        if old_node_hash != new_node_hash:
            changes.append(
                _figma_screen_change(
                    change_type="figma_screen_node_modified",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=old_node_hash,
                    new_hash=new_node_hash,
                    summary=f"Figma screen node changed: {screen_label} in {section_label}.",
                    item=new_item,
                )
            )

        if old_item.get("vision_analysis_hash") != new_item.get("vision_analysis_hash"):
            changes.append(
                _figma_screen_change(
                    change_type="figma_vision_analysis_changed",
                    source_type="figma_screen",
                    source_id=source_id,
                    old_hash=old_item.get("vision_analysis_hash"),
                    new_hash=new_item.get("vision_analysis_hash"),
                    summary=f"Figma vision analysis changed: {screen_label} in {section_label}.",
                    item=new_item,
                )
            )


def compare_jira_snapshots(old_snapshot: dict, new_snapshot: dict) -> list[dict]:
    changes: list[dict] = []
    old_hashes = old_snapshot.get("field_hashes", {}) if isinstance(old_snapshot, dict) else {}
    new_hashes = new_snapshot.get("field_hashes", {}) if isinstance(new_snapshot, dict) else {}

    field_checks = [
        (
            "summary_hash",
            "summary",
            "summary_modified",
            "Jira summary changed.",
        ),
        (
            "description_hash",
            "description",
            "description_modified",
            "Jira description changed.",
        ),
        (
            "acceptance_criteria_hash",
            "acceptance_criteria",
            "acceptance_criteria_modified",
            "Jira acceptance criteria changed.",
        ),
    ]

    for hash_key, source_id, change_type, summary in field_checks:
        old_hash = old_hashes.get(hash_key)
        new_hash = new_hashes.get(hash_key)

        if old_hash != new_hash:
            changes.append(
                _field_change(
                    change_type=change_type,
                    source_id=source_id,
                    old_hash=old_hash,
                    new_hash=new_hash,
                    summary=summary,
                )
            )

    _append_inventory_changes(
        changes,
        source_type="comment",
        old_items=_inventory_map(old_snapshot.get("comments_inventory", []), "comment_id"),
        new_items=_inventory_map(new_snapshot.get("comments_inventory", []), "comment_id"),
        add_type="comment_added",
        modify_type="comment_modified",
        remove_type="comment_removed",
    )
    _append_inventory_changes(
        changes,
        source_type="subtask",
        old_items=_inventory_map(old_snapshot.get("subtasks_inventory", []), "subtask_key"),
        new_items=_inventory_map(new_snapshot.get("subtasks_inventory", []), "subtask_key"),
        add_type="subtask_added",
        modify_type="subtask_modified",
        remove_type="subtask_removed",
    )
    _append_inventory_changes(
        changes,
        source_type="attachment",
        old_items=_map_by_key(old_snapshot.get("attachments_inventory", []), _attachment_key),
        new_items=_map_by_key(new_snapshot.get("attachments_inventory", []), _attachment_key),
        add_type="attachment_added",
        modify_type="attachment_modified",
        remove_type="attachment_removed",
    )
    _append_inventory_changes(
        changes,
        source_type="figma_link",
        old_items=_map_by_key(old_snapshot.get("figma_links_inventory", []), _figma_key),
        new_items=_map_by_key(new_snapshot.get("figma_links_inventory", []), _figma_key),
        add_type="figma_link_added",
        modify_type="figma_link_modified",
        remove_type="figma_link_removed",
    )
    _append_figma_screen_changes(
        changes,
        old_screens=old_snapshot.get("figma_screen_inventory", []),
        new_screens=new_snapshot.get("figma_screen_inventory", []),
    )

    for index, change in enumerate(changes, start=1):
        change["change_id"] = f"CHG-{index:03d}"

    return changes


def _overall_recommended_action(changes: list[dict]) -> str:
    if not changes:
        return ACTION_NO_CHANGE

    return max(
        (item.get("recommended_action", ACTION_NO_CHANGE) for item in changes),
        key=lambda action: ACTION_RANK.get(action, 0),
    )


def _change_counts(changes: list[dict]) -> dict[str, int]:
    counts = {}

    for change in changes:
        change_type = change.get("change_type", "")
        counts[change_type] = counts.get(change_type, 0) + 1

    return counts


def _group_changes_for_display(changes: list[dict]) -> dict[str, list[dict]]:
    groups = {
        "changed_fields": [],
        "added_comments": [],
        "modified_comments": [],
        "added_subtasks": [],
        "modified_subtasks": [],
        "attachment_changes": [],
        "figma_link_changes": [],
        "figma_page_changes": [],
        "figma_section_changes": [],
        "figma_screen_changes": [],
    }

    for change in changes:
        change_type = change.get("change_type")

        if change.get("source_type") == "field":
            groups["changed_fields"].append(change)
        elif change_type == "comment_added":
            groups["added_comments"].append(change)
        elif change_type == "comment_modified":
            groups["modified_comments"].append(change)
        elif change_type == "subtask_added":
            groups["added_subtasks"].append(change)
        elif change_type == "subtask_modified":
            groups["modified_subtasks"].append(change)
        elif change.get("source_type") == "attachment":
            groups["attachment_changes"].append(change)
        elif change.get("source_type") == "figma_link":
            groups["figma_link_changes"].append(change)
        elif change.get("source_type") == "figma_page":
            groups["figma_page_changes"].append(change)
        elif change.get("source_type") == "figma_section":
            groups["figma_section_changes"].append(change)
        elif change.get("source_type") == "figma_screen":
            groups["figma_screen_changes"].append(change)

    return groups


def build_change_impact_report(
    ticket_id: str,
    old_snapshot: dict,
    new_snapshot: dict,
) -> dict:
    changes = compare_jira_snapshots(old_snapshot, new_snapshot)
    old_version = (old_snapshot.get("metadata", {}) or {}).get("snapshot_version")
    new_version = (new_snapshot.get("metadata", {}) or {}).get("snapshot_version")
    recommended_action = _overall_recommended_action(changes)

    return {
        "ticket_id": ticket_id,
        "report_version": _get_next_change_report_version(ticket_id),
        "created_at": _utc_now(),
        "old_snapshot_version": old_version,
        "new_snapshot_version": new_version,
        "jira_updated_old": (old_snapshot.get("metadata", {}) or {}).get("jira_updated", ""),
        "jira_updated_new": (new_snapshot.get("metadata", {}) or {}).get("jira_updated", ""),
        "change_count": len(changes),
        "change_counts": _change_counts(changes),
        "recommended_action": recommended_action,
        "changes": changes,
        "display_groups": _group_changes_for_display(changes),
    }


def _report_markdown(report: dict) -> str:
    lines = [
        f"# Jira Change Impact Report: {report.get('ticket_id', '')}",
        "",
        f"- Report version: {report.get('report_version')}",
        f"- Old snapshot: {report.get('old_snapshot_version')}",
        f"- New snapshot: {report.get('new_snapshot_version')}",
        f"- Change count: {report.get('change_count', 0)}",
        f"- Recommended action: {report.get('recommended_action', ACTION_NO_CHANGE)}",
        "",
        "## Changes",
        "",
    ]

    changes = report.get("changes", [])

    if not changes:
        lines.append("No Jira source changes detected.")
    else:
        for change in changes:
            screen_details = []

            if change.get("screen_name"):
                screen_details.append(f"- Screen: {change.get('screen_name')}")
            if change.get("section_name"):
                screen_details.append(f"- Section: {change.get('section_name')}")
            if change.get("image_path"):
                screen_details.append(f"- Image path: {change.get('image_path')}")

            lines.extend(
                [
                    f"### {change.get('change_id')} {change.get('change_type')}",
                    "",
                    f"- Source: {change.get('source_type')} / {change.get('source_id')}",
                    f"- Recommended action: {change.get('recommended_action')}",
                    f"- Impact confidence: {change.get('impact_confidence')}",
                    f"- Summary: {change.get('summary')}",
                    *screen_details,
                    "",
                ]
            )

    return "\n".join(lines).strip() + "\n"


def save_change_impact_report(ticket_id: str, report: dict) -> dict:
    version = int(report.get("report_version") or _get_next_change_report_version(ticket_id))
    report["ticket_id"] = ticket_id
    report["report_version"] = version

    json_file = _change_report_file(ticket_id, version, "json")
    markdown_file = _change_report_file(ticket_id, version, "md")
    latest_file = _latest_change_report_file(ticket_id)

    _write_json(json_file, report)
    markdown_file.parent.mkdir(parents=True, exist_ok=True)
    markdown_file.write_text(_report_markdown(report), encoding="utf-8")
    _write_json(latest_file, report)

    return {
        "report_version": version,
        "report_path": str(json_file),
        "report_markdown_path": str(markdown_file),
        "latest_report_path": str(latest_file),
    }


def load_latest_change_impact_report(ticket_id: str) -> dict | None:
    return _read_json(_latest_change_report_file(ticket_id), None)


def fetch_latest_jira_payload_for_snapshot(
    ticket_id: str,
    jira_pat: str = "",
) -> dict:
    from app.services.jira_requirement_service import (
        _get_issue_comments,
        _get_jira_client,
        _get_subtask_keys,
    )

    root = REQUIREMENTS_ROOT / ticket_id
    ticket = _read_json(root / "ticket.json", {}) or {}
    issue_key = str(ticket.get("jira_key") or ticket_id).strip().upper()

    if not issue_key:
        raise ValueError(f"Missing Jira key for {ticket_id}.")

    jira = _get_jira_client(jira_pat=jira_pat)
    fields = "summary,description,comment,attachment,subtasks,status,issuetype,updated"
    main_issue = jira.issue(issue_key, fields=fields)
    main_issue.setdefault("fields", {})["comment"] = {
        "comments": _get_issue_comments(jira, issue_key)
    }
    included_issues = []

    for subtask_key in _get_subtask_keys(main_issue):
        sub_issue = jira.issue(subtask_key, fields=fields)
        sub_issue.setdefault("fields", {})["comment"] = {
            "comments": _get_issue_comments(jira, subtask_key)
        }
        included_issues.append(sub_issue)

    main_issue["_included_issues"] = included_issues
    return main_issue


def sync_jira_changes_for_requirement(
    ticket_id: str,
    jira_pat: str = "",
) -> dict:
    previous_snapshot = load_latest_jira_snapshot(ticket_id)
    root = REQUIREMENTS_ROOT / ticket_id
    normalized_text = _read_text(root / "analysis" / "sanitized_requirement.md")
    latest_payload = fetch_latest_jira_payload_for_snapshot(
        ticket_id=ticket_id,
        jira_pat=jira_pat,
    )
    new_snapshot = build_jira_snapshot(
        ticket_id=ticket_id,
        jira_payload=latest_payload,
        normalized_requirement_text=normalized_text or None,
        source_root=root,
    )

    if not previous_snapshot:
        save_result = save_jira_snapshot(ticket_id, new_snapshot)
        initial_report = {
            "ticket_id": ticket_id,
            "report_version": _get_next_change_report_version(ticket_id),
            "created_at": _utc_now(),
            "old_snapshot_version": None,
            "new_snapshot_version": new_snapshot.get("metadata", {}).get("snapshot_version"),
            "jira_updated_old": "",
            "jira_updated_new": new_snapshot.get("metadata", {}).get("jira_updated", ""),
            "change_count": 0,
            "change_counts": {},
            "recommended_action": ACTION_NO_CHANGE,
            "message": "Initial snapshot created. No previous version to compare.",
            "changes": [],
            "display_groups": _group_changes_for_display([]),
        }
        save_change_impact_report(ticket_id, initial_report)

        return {
            **save_result,
            "message": "Initial snapshot created. No previous version to compare.",
            "change_count": 0,
            "recommended_action": ACTION_NO_CHANGE,
        }

    report = build_change_impact_report(
        ticket_id=ticket_id,
        old_snapshot=previous_snapshot,
        new_snapshot=new_snapshot,
    )
    save_snapshot_result = save_jira_snapshot(ticket_id, new_snapshot)
    save_report_result = save_change_impact_report(ticket_id, report)

    return {
        "ticket_id": ticket_id,
        "message": "Jira sync completed.",
        "snapshot_version": save_snapshot_result["snapshot_version"],
        "snapshot_path": save_snapshot_result["snapshot_path"],
        "report_version": save_report_result["report_version"],
        "report_path": save_report_result["report_path"],
        "report_markdown_path": save_report_result["report_markdown_path"],
        "change_count": report["change_count"],
        "change_counts": report["change_counts"],
        "recommended_action": report["recommended_action"],
    }
