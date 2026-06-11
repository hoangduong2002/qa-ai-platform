import json
import html
import os
import re
import time
import traceback
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests

from app.services.local_ai_config_service import (
    is_figma_local_vision_enabled,
)


REQUIREMENTS_ROOT = Path("requirements")
FIGMA_API_BASE_URL = "https://api.figma.com/v1"
FIGMA_IMAGE_EXPORT_SKIPPED_MESSAGE = (
    "Figma image export skipped or unavailable for this screen."
)
VISION_ANALYSIS_SKIPPED_MESSAGE = (
    "Vision analysis skipped because local vision analysis is disabled."
)


FIGMA_IMAGE_ANALYSIS_PROMPT = """
You are analyzing a Figma-exported UI screen for QA requirement extraction.

Use only what is visible in the image.
Do not invent business rules, hidden requirements, validation rules, navigation items, or user flows.

Return Markdown:

# Screen Summary
Maximum 3 sentences.

# Visible UI Text
List only clearly readable text. Do not repeat. Use [UNREADABLE] if unclear.

# UI Elements
List visible fields, buttons, tabs, tables, dialogs, checkboxes, radio buttons, icons, sections, and messages.

# Layout / Screen Structure
Describe visible sections and grouping only.

# Possible User Actions
List only actions directly supported by visible UI controls.

# Potential QA Notes
List direct QA observations only. Do not create full test cases.

Rules:
- Do not infer domain unless visible text clearly indicates it.
- Do not create validation rules unless error message, required marker, format hint, or constraint is visible.
- Prefer [UNCLEAR] over guessing.
- Keep concise.
""".strip()


@dataclass
class FigmaFileReference:
    file_key: str
    source_urls: list[str]
    entry_node_ids: list[str]


@dataclass
class FigmaPageScope:
    file_key: str
    page_id: str
    page_name: str
    entry_node_ids: list[str]
    source_links: list[str] = field(default_factory=list)
    duplicate_link_count: int = 0
    skipped_duplicate_pages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FigmaLayerRef:
    node_id: str
    name: str
    type: str
    page_id: str
    page_name: str
    width: float
    height: float


@dataclass
class FigmaScreenRef:
    node_id: str
    name: str
    type: str
    page_id: str
    page_name: str
    layer_id: str
    layer_name: str
    width: float
    height: float
    text_count: int


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.exists():
            path.unlink()


def _get_figma_token() -> str:
    token = os.getenv("FIGMA_ACCESS_TOKEN", "").strip()

    if not token:
        raise ValueError(
            "FIGMA_ACCESS_TOKEN is missing. "
            "Please create a Figma access token and set it in .env."
        )

    return token


def _figma_headers() -> dict[str, str]:
    return {
        "X-Figma-Token": _get_figma_token(),
        "Accept": "application/json",
        "User-Agent": "qa-ai-platform/1.0",
    }


def _safe_name(value: str) -> str:
    value = value or "unknown"
    value = value.replace(":", "_")
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    return value.strip("_") or "unknown"


def _normalize_node_id(value: str) -> str:
    value = urllib.parse.unquote(value or "").strip()
    value = value.replace("-", ":")
    return value


def _extract_file_key_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]

    for idx, part in enumerate(parts):
        if part in {"design", "file", "proto"} and idx + 1 < len(parts):
            return parts[idx + 1]

    return None


def _extract_node_ids_from_url(url: str) -> list[str]:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    candidate_keys = [
        "node-id",
        "node_id",
        "starting-point-node-id",
        "selected-node-id",
    ]

    node_ids: list[str] = []

    for key in candidate_keys:
        for value in query.get(key, []):
            normalized = _normalize_node_id(value)
            if normalized and normalized not in node_ids:
                node_ids.append(normalized)

    return node_ids


def extract_figma_urls(text: str) -> list[str]:
    if not text:
        return []

    text = html.unescape(text)

    pattern = re.compile(
        r"https://(?:www\.)?figma\.com/(?:design|file|proto)/[^\s\]\)\}<>\"'\\]+",
        flags=re.IGNORECASE,
    )

    urls: list[str] = []

    for match in pattern.findall(text):
        url = match.rstrip(".,;\\")
        if url not in urls:
            urls.append(url)

    return urls


def extract_figma_references_from_texts(
    texts: list[str],
) -> list[FigmaFileReference]:
    grouped: dict[str, FigmaFileReference] = {}

    for text in texts:
        for url in extract_figma_urls(text):
            file_key = _extract_file_key_from_url(url)

            if not file_key:
                continue

            if file_key not in grouped:
                grouped[file_key] = FigmaFileReference(
                    file_key=file_key,
                    source_urls=[],
                    entry_node_ids=[],
                )

            if url not in grouped[file_key].source_urls:
                grouped[file_key].source_urls.append(url)

            for node_id in _extract_node_ids_from_url(url):
                if node_id not in grouped[file_key].entry_node_ids:
                    grouped[file_key].entry_node_ids.append(node_id)

    return list(grouped.values())


def extract_figma_link_records_from_sources(
    sources: list[dict[str, str]],
    detected_before_sanitizer: bool = True,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen = set()

    for source in sources:
        source_name = source.get("source", "")
        text = source.get("text", "")

        for url in extract_figma_urls(text):
            key = (url, source_name)

            if key in seen:
                continue

            seen.add(key)

            records.append(
                {
                    "url": url,
                    "file_key": _extract_file_key_from_url(url) or "",
                    "node_ids": _extract_node_ids_from_url(url),
                    "source": source_name,
                    "detected_before_sanitizer": detected_before_sanitizer,
                }
            )

    return records


def _write_json_pretty(output_file: Path, payload: Any) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_json_compact(output_file: Path, payload: Any) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def fetch_figma_file(
    file_key: str,
    depth: int | None = None,
) -> dict[str, Any]:
    url = f"{FIGMA_API_BASE_URL}/files/{file_key}"

    params: dict[str, str] = {}

    if depth is not None:
        params["depth"] = str(depth)

    response = requests.get(
        url,
        headers=_figma_headers(),
        params=params,
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch Figma file. "
            f"file_key={file_key}, depth={depth}, "
            f"status={response.status_code}, body={response.text[:1000]}"
        )

    return response.json()


def fetch_figma_file_depth1(file_key: str) -> dict[str, Any]:
    return fetch_figma_file(file_key=file_key, depth=1)


def fetch_figma_nodes(
    file_key: str,
    node_ids: list[str],
    depth: int | None = 3,
) -> dict[str, Any]:
    if not node_ids:
        return {}

    url = f"{FIGMA_API_BASE_URL}/files/{file_key}/nodes"

    params: dict[str, str] = {
        "ids": ",".join(node_ids),
    }

    if depth is not None:
        params["depth"] = str(depth)

    response = requests.get(
        url,
        headers=_figma_headers(),
        params=params,
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch Figma nodes. "
            f"file_key={file_key}, node_count={len(node_ids)}, depth={depth}, "
            f"status={response.status_code}, body={response.text[:1000]}"
        )

    return response.json()


def fetch_single_figma_node(
    file_key: str,
    node_id: str,
    depth: int | None = 3,
) -> dict[str, Any]:
    data = fetch_figma_nodes(
        file_key=file_key,
        node_ids=[node_id],
        depth=depth,
    )

    return (data.get("nodes") or {}).get(node_id) or {}


def _get_pages_from_file_shell(file_json: dict[str, Any]) -> list[dict[str, Any]]:
    document = file_json.get("document") or {}
    pages = document.get("children") or []
    return [page for page in pages if page.get("type") == "CANVAS"]


def _node_tree_contains_id(node: dict[str, Any], target_id: str) -> bool:
    if not node or not target_id:
        return False

    if node.get("id") == target_id:
        return True

    for child in node.get("children") or []:
        if _node_tree_contains_id(child, target_id):
            return True

    return False


def resolve_target_pages(
    file_key: str,
    entry_node_ids: list[str],
) -> list[FigmaPageScope]:
    file_shell = fetch_figma_file_depth1(file_key)
    pages = _get_pages_from_file_shell(file_shell)

    if not pages:
        return []

    if not entry_node_ids:
        if _env_bool("FIGMA_ALLOW_FIRST_PAGE_FALLBACK", False):
            first_page = pages[0]
            return [
                FigmaPageScope(
                    file_key=file_key,
                    page_id=first_page.get("id", ""),
                    page_name=first_page.get("name", ""),
                    entry_node_ids=[],
                )
            ]

        raise RuntimeError(
            "Figma link does not contain node-id. "
            "Cannot resolve target page safely. "
            "Set FIGMA_ALLOW_FIRST_PAGE_FALLBACK=true to use first page fallback."
        )

    resolve_depth = _env_int("FIGMA_PAGE_RESOLVE_DEPTH", 4)
    resolved_pages: dict[str, FigmaPageScope] = {}

    for page in pages:
        page_id = page.get("id", "")
        page_name = page.get("name", "")

        if not page_id:
            continue

        try:
            page_payload = fetch_single_figma_node(
                file_key=file_key,
                node_id=page_id,
                depth=resolve_depth,
            )
        except Exception:
            continue

        page_document = page_payload.get("document") or {}

        matched_entry_ids = [
            entry_node_id
            for entry_node_id in entry_node_ids
            if _node_tree_contains_id(page_document, entry_node_id)
        ]

        if matched_entry_ids:
            resolved_pages[page_id] = FigmaPageScope(
                file_key=file_key,
                page_id=page_id,
                page_name=page_name,
                entry_node_ids=matched_entry_ids,
            )

    if not resolved_pages:
        raise RuntimeError(
            f"Cannot resolve target Figma page from entry node ids: {entry_node_ids}. "
            f"Try increasing FIGMA_PAGE_RESOLVE_DEPTH."
        )

    return list(resolved_pages.values())


def _source_links_for_page_scope(
    reference: FigmaFileReference,
    page_scope: FigmaPageScope,
) -> list[str]:
    matched_links: list[str] = []
    page_entry_node_ids = set(page_scope.entry_node_ids)

    for url in reference.source_urls:
        url_node_ids = set(_extract_node_ids_from_url(url))

        if url_node_ids and page_entry_node_ids.intersection(url_node_ids):
            matched_links.append(url)

    if not matched_links and len(reference.source_urls) == 1:
        matched_links.append(reference.source_urls[0])

    return matched_links


def _dedupe_page_scopes(
    reference: FigmaFileReference,
    page_scopes: list[FigmaPageScope],
) -> list[FigmaPageScope]:
    deduped: dict[tuple[str, str], FigmaPageScope] = {}

    for page_scope in page_scopes:
        key = (page_scope.file_key, page_scope.page_id)
        source_links = _source_links_for_page_scope(
            reference=reference,
            page_scope=page_scope,
        )

        if key not in deduped:
            page_scope.source_links = []
            page_scope.skipped_duplicate_pages = []

            for source_link in source_links:
                if source_link not in page_scope.source_links:
                    page_scope.source_links.append(source_link)

            page_scope.duplicate_link_count = max(
                len(page_scope.source_links) - 1,
                0,
            )
            deduped[key] = page_scope
            continue

        existing = deduped[key]

        for entry_node_id in page_scope.entry_node_ids:
            if entry_node_id not in existing.entry_node_ids:
                existing.entry_node_ids.append(entry_node_id)

        for source_link in source_links:
            if source_link not in existing.source_links:
                existing.source_links.append(source_link)

        existing.duplicate_link_count = max(
            len(existing.source_links) - 1,
            0,
        )

    for page_scope in deduped.values():
        if not page_scope.source_links:
            page_scope.source_links = list(reference.source_urls)

        page_scope.duplicate_link_count = max(
            len(page_scope.source_links) - 1,
            0,
        )

        page_scope.skipped_duplicate_pages = []

        if page_scope.duplicate_link_count:
            for source_link in page_scope.source_links[1:]:
                page_scope.skipped_duplicate_pages.append(
                    {
                        "file_key": page_scope.file_key,
                        "page_id": page_scope.page_id,
                        "page_name": page_scope.page_name,
                        "source_link": source_link,
                        "reason": "duplicate link resolved to already exported page",
                    }
                )

    return list(deduped.values())


def _extract_size(node: dict[str, Any]) -> tuple[float, float]:
    box = node.get("absoluteBoundingBox") or {}
    width = float(box.get("width") or 0)
    height = float(box.get("height") or 0)
    return width, height


def _count_text_descendants(node: dict[str, Any]) -> int:
    count = 1 if node.get("type") == "TEXT" and node.get("characters") else 0

    for child in node.get("children") or []:
        count += _count_text_descendants(child)

    return count


def _should_skip_layer_by_name(name: str) -> bool:
    normalized = (name or "").lower().strip()

    # Keep this blacklist much lighter than screen/node blacklist.
    exact_blacklist = {
        "icons",
        "icon",
        "logos",
        "logo",
        "trash",
        "archive",
    }

    return normalized in exact_blacklist


def _should_skip_node_by_name(name: str) -> bool:
    normalized = (name or "").lower()

    blacklist = [
        "icon",
        "icons",
        "logo",
        "avatar",
        "divider",
        "spacer",
        "background",
        "mask",
        "shadow",
        "decorator",
        "thumbnail",
        "cover",
    ]

    return any(word in normalized for word in blacklist)


def _is_reasonable_layer_size(width: float, height: float) -> bool:
    min_width = _env_int("FIGMA_MIN_FRAME_WIDTH", 200)
    min_height = _env_int("FIGMA_MIN_FRAME_HEIGHT", 200)

    max_area = _env_int("FIGMA_MAX_LAYER_AREA", 50_000_000)
    max_width = _env_int("FIGMA_MAX_LAYER_WIDTH", 20000)
    max_height = _env_int("FIGMA_MAX_LAYER_HEIGHT", 20000)

    area = width * height

    return (
        width >= min_width
        and height >= min_height
        and width <= max_width
        and height <= max_height
        and area <= max_area
    )


def _is_reasonable_size(width: float, height: float) -> bool:
    min_width = _env_int("FIGMA_MIN_FRAME_WIDTH", 200)
    min_height = _env_int("FIGMA_MIN_FRAME_HEIGHT", 200)

    max_area = _env_int("FIGMA_MAX_FRAME_AREA", 3_000_000)
    max_width = _env_int("FIGMA_MAX_FRAME_WIDTH", 2500)
    max_height = _env_int("FIGMA_MAX_FRAME_HEIGHT", 2500)

    area = width * height

    return (
        width >= min_width
        and height >= min_height
        and width <= max_width
        and height <= max_height
        and area <= max_area
    )


def _is_layer_candidate(node: dict[str, Any]) -> bool:
    node_type = node.get("type", "")
    node_id = node.get("id", "")

    return bool(node_id) and node_type == "SECTION"


def _is_screen_candidate(node: dict[str, Any]) -> bool:
    node_type = node.get("type", "")
    node_id = node.get("id", "")

    return bool(node_id) and node_type == "FRAME"


def _explain_screen_candidate(node: dict[str, Any]) -> str:
    node_type = node.get("type", "")
    node_id = node.get("id", "")

    if not node_id:
        return "missing node id"

    if node_type in {"VECTOR", "LINE"}:
        return "flow connector debug only"

    if node_type != "FRAME":
        return f"unsupported screen type: {node_type}"

    return "accepted frame screen"
    
    
def _explain_layer_candidate(node: dict[str, Any]) -> str:
    node_type = node.get("type", "")
    node_id = node.get("id", "")

    if not node_id:
        return "missing node id"

    if node_type == "SECTION":
        return "accepted section container"

    if node_type in {"VECTOR", "LINE"}:
        return "flow connector debug only"

    return f"unsupported layer type: {node_type}"


def collect_layers_from_page(
    page_scope: FigmaPageScope,
    page_document: dict[str, Any],
) -> list[FigmaLayerRef]:
    layers: list[FigmaLayerRef] = []
    max_layer_scan_depth = _env_int("FIGMA_LAYER_SCAN_DEPTH", 2)

    def walk(node: dict[str, Any], depth: int) -> None:
        if depth > max_layer_scan_depth:
            return

        if depth > 0 and _is_layer_candidate(node):
            width, height = _extract_size(node)

            layers.append(
                FigmaLayerRef(
                    node_id=node.get("id", ""),
                    name=node.get("name", ""),
                    type=node.get("type", ""),
                    page_id=page_scope.page_id,
                    page_name=page_scope.page_name,
                    width=width,
                    height=height,
                )
            )

        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(page_document, depth=0)

    # Deduplicate by node_id.
    deduped: list[FigmaLayerRef] = []
    seen = set()

    for layer in layers:
        if layer.node_id in seen:
            continue
        seen.add(layer.node_id)
        deduped.append(layer)

    return deduped


def collect_screens_from_layer_document(
    page_scope: FigmaPageScope,
    layer_ref: FigmaLayerRef,
    layer_document: dict[str, Any],
) -> list[FigmaScreenRef]:
    screens: list[FigmaScreenRef] = []

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        if not node:
            return

        node_id = node.get("id", "")

        if depth > 0 and _is_screen_candidate(node):
            width, height = _extract_size(node)
            text_count = _count_text_descendants(node)

            screens.append(
                FigmaScreenRef(
                    node_id=node_id,
                    name=node.get("name", ""),
                    type=node.get("type", ""),
                    page_id=page_scope.page_id,
                    page_name=page_scope.page_name,
                    layer_id=layer_ref.node_id,
                    layer_name=layer_ref.name,
                    width=width,
                    height=height,
                    text_count=text_count,
                )
            )

            # Treat this as a screen. Do not collect nested frames inside screen.
            return

        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(layer_document, depth=0)

    return screens


def _collect_flow_connectors_debug(
    node: dict[str, Any],
    scope_id: str,
    scope_name: str,
    scope_type: str,
    stop_at_section: bool = False,
) -> list[dict[str, Any]]:
    connectors: list[dict[str, Any]] = []

    def walk(item: dict[str, Any], depth: int, path: list[str]) -> None:
        if not item:
            return

        node_type = item.get("type", "")
        node_id = item.get("id", "")
        name = item.get("name", "")
        next_path = [*path, name or node_id or node_type or "unknown"]

        if node_type in {"VECTOR", "LINE"}:
            width, height = _extract_size(item)
            connectors.append(
                {
                    "id": node_id,
                    "name": name,
                    "type": node_type,
                    "scope_id": scope_id,
                    "scope_name": scope_name,
                    "scope_type": scope_type,
                    "depth": depth,
                    "path": next_path,
                    "size": {
                        "width": width,
                        "height": height,
                        "area": width * height,
                    },
                    "decision": "debug_only",
                    "reason": "VECTOR/LINE flow connector handling is not implemented",
                }
            )

        if depth > 0 and node_type == "FRAME":
            return

        if depth > 0 and stop_at_section and node_type == "SECTION":
            return

        for child in item.get("children") or []:
            walk(child, depth + 1, next_path)

    walk(node, depth=0, path=[])

    return connectors


def _build_layer_screen_debug(
    layer_ref: FigmaLayerRef,
    layer_document: dict[str, Any],
    included_screen_ids: set[str],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        if not node:
            return

        node_id = node.get("id", "")
        width, height = _extract_size(node)
        reason = _explain_screen_candidate(node)
        included = node_id in included_screen_ids

        nodes.append(
            {
                "id": node_id,
                "name": node.get("name"),
                "type": node.get("type"),
                "depth": depth,
                "size": {
                    "width": width,
                    "height": height,
                    "area": width * height,
                },
                "text_count": _count_text_descendants(node),
                "included_as_screen": included,
                "decision": "included" if included else "skipped",
                "reason": "included in extracted screens" if included else reason,
            }
        )

        if depth > 0 and node.get("type") == "FRAME":
            return

        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(layer_document, depth=0)

    return {
        "layer": asdict(layer_ref),
        "included_screen_ids": sorted(included_screen_ids),
        "nodes": nodes,
    }


def collect_screens_for_page(
    file_key: str,
    page_scope: FigmaPageScope,
    output_root: Path,
) -> tuple[list[FigmaLayerRef], list[FigmaScreenRef], dict[str, dict[str, Any]]]:
    page_fetch_depth = _env_int("FIGMA_PAGE_FETCH_DEPTH", 3)
    layer_fetch_depth = _env_int("FIGMA_LAYER_FETCH_DEPTH", 4)

    page_payload = fetch_single_figma_node(
        file_key=file_key,
        node_id=page_scope.page_id,
        depth=page_fetch_depth,
    )

    page_document = page_payload.get("document") or {}
    
    page_children_debug = []

    for child in page_document.get("children") or []:
        candidate_reason = _explain_layer_candidate(child)
        page_children_debug.append(
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "type": child.get("type"),
                "size": _extract_size(child),
                "included_as_layer": candidate_reason.startswith("accepted"),
                "decision": (
                    "included"
                    if candidate_reason.startswith("accepted")
                    else "skipped"
                ),
                "reason": candidate_reason,
            }
        )

    _write_json_pretty(
        output_root / "page_children_debug.json",
        page_children_debug,
    )

    _write_json_compact(
        output_root / "target_page.json",
        page_payload,
    )

    flow_connectors_debug = _collect_flow_connectors_debug(
        node=page_document,
        scope_id=page_scope.page_id,
        scope_name=page_scope.page_name,
        scope_type=page_document.get("type", "CANVAS"),
        stop_at_section=True,
    )

    layers = collect_layers_from_page(
        page_scope=page_scope,
        page_document=page_document,
    )

    all_screens: list[FigmaScreenRef] = []
    screen_documents: dict[str, dict[str, Any]] = {}
    layer_screen_debug: list[dict[str, Any]] = []

    for layer in layers:
        try:
            layer_payload = fetch_single_figma_node(
                file_key=file_key,
                node_id=layer.node_id,
                depth=layer_fetch_depth,
            )
        except Exception as error:
            layer_error_file = (
                output_root
                / "layers"
                / _safe_name(layer.node_id)
                / "layer_fetch_error.txt"
            )
            layer_error_file.parent.mkdir(parents=True, exist_ok=True)
            layer_error_file.write_text(
                "".join(
                    traceback.format_exception(
                        type(error),
                        error,
                        error.__traceback__,
                    )
                ),
                encoding="utf-8",
            )
            layer_screen_debug.append(
                {
                    "layer": asdict(layer),
                    "included_screen_ids": [],
                    "fetch_error": repr(error),
                    "nodes": [],
                }
            )
            continue

        layer_document = layer_payload.get("document") or {}
        flow_connectors_debug.extend(
            _collect_flow_connectors_debug(
                node=layer_document,
                scope_id=layer.node_id,
                scope_name=layer.name,
                scope_type=layer.type,
            )
        )

        layer_dir = output_root / "layers" / _safe_name(layer.node_id)
        layer_dir.mkdir(parents=True, exist_ok=True)

        _write_json_compact(
            layer_dir / "layer.json",
            layer_payload,
        )

        screens = collect_screens_from_layer_document(
            page_scope=page_scope,
            layer_ref=layer,
            layer_document=layer_document,
        )

        layer_screen_debug.append(
            _build_layer_screen_debug(
                layer_ref=layer,
                layer_document=layer_document,
                included_screen_ids={screen.node_id for screen in screens},
            )
        )

        for screen in screens:
            if screen.node_id not in screen_documents:
                all_screens.append(screen)

                screen_documents[screen.node_id] = _find_node_by_id(
                    layer_document,
                    screen.node_id,
                ) or {}

        time.sleep(0.1)

    _write_json_pretty(
        output_root / "flow_connectors_debug.json",
        flow_connectors_debug,
    )

    _write_json_pretty(
        output_root / "layer_screen_debug.json",
        layer_screen_debug,
    )

    return layers, all_screens, screen_documents


def _find_node_by_id(
    node: dict[str, Any],
    node_id: str,
) -> dict[str, Any] | None:
    if not node:
        return None

    if node.get("id") == node_id:
        return node

    for child in node.get("children") or []:
        found = _find_node_by_id(child, node_id)
        if found:
            return found

    return None


def _chunk_list(items: list[str], chunk_size: int) -> list[list[str]]:
    chunk_size = max(chunk_size, 1)

    return [
        items[index:index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _get_figma_image_urls_once(
    file_key: str,
    node_ids: list[str],
    scale: str,
) -> dict[str, str]:
    if not node_ids:
        return {}

    export_format = os.getenv("FIGMA_EXPORT_FORMAT", "png").strip() or "png"

    url = f"{FIGMA_API_BASE_URL}/images/{file_key}"

    response = requests.get(
        url,
        headers=_figma_headers(),
        params={
            "ids": ",".join(node_ids),
            "format": export_format,
            "scale": scale,
        },
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to get Figma image URLs. "
            f"file_key={file_key}, node_count={len(node_ids)}, scale={scale}, "
            f"status={response.status_code}, body={response.text[:1000]}"
        )

    data = response.json()
    return data.get("images") or {}


def _is_figma_rate_limit_error(error: Exception) -> bool:
    return "status=429" in str(error) or "Rate limit exceeded" in str(error)


def _get_figma_image_urls_with_retry(
    file_key: str,
    node_ids: list[str],
    scale: str,
) -> dict[str, str]:
    max_attempts = _env_int("FIGMA_RATE_LIMIT_MAX_ATTEMPTS", 3)
    sleep_seconds = _env_int("FIGMA_RATE_LIMIT_SLEEP_SECONDS", 10)

    for attempt in range(1, max_attempts + 1):
        try:
            return _get_figma_image_urls_once(
                file_key=file_key,
                node_ids=node_ids,
                scale=scale,
            )
        except RuntimeError as error:
            if not _is_figma_rate_limit_error(error) or attempt >= max_attempts:
                raise

            time.sleep(sleep_seconds)

    return {}


def get_figma_image_urls(
    file_key: str,
    node_ids: list[str],
) -> dict[str, str]:
    if not node_ids:
        return {}

    batch_size = _env_int("FIGMA_IMAGE_EXPORT_BATCH_SIZE", 1)
    export_scale = os.getenv("FIGMA_EXPORT_SCALE", "1").strip() or "1"

    all_images: dict[str, str] = {}

    for batch in _chunk_list(node_ids, batch_size):
        try:
            images = _get_figma_image_urls_with_retry(
                file_key=file_key,
                node_ids=batch,
                scale=export_scale,
            )
            all_images.update(images)

        except RuntimeError as error:
            error_text = str(error)

            if _is_figma_rate_limit_error(error):
                print(
                    f"Skipped Figma image export batch after rate limit retries. "
                    f"node_count={len(batch)}"
                )
                continue

            if (
                "Render timeout" not in error_text
                and "try requesting fewer" not in error_text
            ):
                raise

            for node_id in batch:
                try:
                    images = _get_figma_image_urls_with_retry(
                        file_key=file_key,
                        node_ids=[node_id],
                        scale="1",
                    )
                    all_images.update(images)
                except Exception as single_error:
                    print(
                        f"Skipped Figma image export for node {node_id}: "
                        f"{single_error}"
                    )

        time.sleep(0.3)

    return all_images


def download_image(
    image_url: str,
    output_file: Path,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(
        image_url,
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to download Figma exported image. "
            f"status={response.status_code}, body={response.text[:500]}"
        )

    output_file.write_bytes(response.content)


def _extract_text_layers(node: dict[str, Any]) -> list[str]:
    texts: list[str] = []

    def walk(item: dict[str, Any]) -> None:
        if item.get("type") == "TEXT":
            value = (item.get("characters") or "").strip()
            if value and value not in texts:
                texts.append(value)

        for child in item.get("children") or []:
            walk(child)

    walk(node)
    return texts


def _build_screen_context(
    screen: FigmaScreenRef,
    screen_document: dict[str, Any],
    image_file: Path | None,
    vision_analysis: str | None = None,
) -> str:
    texts = _extract_text_layers(screen_document or {})

    lines = [
        f"### Screen: {screen.name}",
        f"- Node ID: {screen.node_id}",
        f"- Type: {screen.type}",
        f"- Page: {screen.page_name}",
        f"- Layer: {screen.layer_name}",
        f"- Size: {int(screen.width)}x{int(screen.height)}",
    ]

    if image_file:
        lines.append(f"- Exported image: {image_file}")
    else:
        lines.append("- Exported image: [NOT AVAILABLE]")

    lines.append("")
    lines.append("#### Figma Text Layers")

    if texts:
        for text in texts[:100]:
            lines.append(f"- {text}")
    else:
        lines.append("- [NO TEXT LAYERS OR NOT FETCHED]")

    if vision_analysis:
        lines.append("")
        lines.append("#### Vision Analysis")
        lines.append(vision_analysis)

    return "\n".join(lines).strip()


def _analyze_with_local_vision(
    image_file: Path | None,
) -> str | None:
    if not image_file:
        return None

    from app.services.gemma_image_extractor_service import extract_image_with_gemma

    return extract_image_with_gemma(
        image_path=image_file,
        prompt=FIGMA_IMAGE_ANALYSIS_PROMPT,
    )


def export_figma_page_scope(
    ticket_id: str,
    reference: FigmaFileReference,
    page_scope: FigmaPageScope,
) -> str:
    output_root = (
        REQUIREMENTS_ROOT
        / ticket_id
        / "source"
        / "figma"
        / _safe_name(reference.file_key)
        / _safe_name(page_scope.page_id)
    )

    output_root.mkdir(parents=True, exist_ok=True)

    page_metadata = {
        "file_key": reference.file_key,
        "source_links": page_scope.source_links or reference.source_urls,
        "source_urls": page_scope.source_links or reference.source_urls,
        "all_file_source_links": reference.source_urls,
        "page_id": page_scope.page_id,
        "page_name": page_scope.page_name,
        "entry_node_ids": page_scope.entry_node_ids,
        "duplicate_link_count": page_scope.duplicate_link_count,
        "skipped_duplicate_pages": page_scope.skipped_duplicate_pages,
        "extract_scope": _env_str("FIGMA_EXTRACT_SCOPE", "linked_page"),
    }

    _write_json_pretty(
        output_root / "page_metadata.json",
        page_metadata,
    )

    layers, screens, screen_documents = collect_screens_for_page(
        file_key=reference.file_key,
        page_scope=page_scope,
        output_root=output_root,
    )

    _write_json_pretty(
        output_root / "extracted_layers.json",
        [asdict(layer) for layer in layers],
    )

    _write_json_pretty(
        output_root / "extracted_screens.json",
        [asdict(screen) for screen in screens],
    )

    screen_ids = [screen.node_id for screen in screens]

    image_export_enabled = _env_bool("FIGMA_IMAGE_EXPORT_ENABLED", True)
    image_urls: dict[str, str] = {}

    print(
        "Figma image export config: "
        f"ticket_id={ticket_id}, file_key={reference.file_key}, "
        f"page_id={page_scope.page_id}, image_export_enabled={image_export_enabled}, "
        f"screen_count={len(screen_ids)}"
    )

    if image_export_enabled:
        try:
            image_urls = get_figma_image_urls(
                file_key=reference.file_key,
                node_ids=screen_ids,
            )
            _remove_file_if_exists(output_root / "image_export_error.txt")
        except Exception as error:
            image_urls = {}
            (output_root / "image_export_error.txt").write_text(
                "".join(
                    traceback.format_exception(
                        type(error),
                        error,
                        error.__traceback__,
                    )
                ),
                encoding="utf-8",
            )

    context_parts = [
        "## Figma Page Context",
        "",
        f"- File key: {reference.file_key}",
        f"- Page: {page_scope.page_name}",
        f"- Page ID: {page_scope.page_id}",
        "- Source URLs:",
        *[f"  - {url}" for url in (page_scope.source_links or reference.source_urls)],
        "",
        "- Entry node IDs:",
        *[f"  - {node_id}" for node_id in page_scope.entry_node_ids],
        "",
        f"- Duplicate links merged into this page: {page_scope.duplicate_link_count}",
        "",
        f"- Extracted layers: {len(layers)}",
        f"- Extracted screens: {len(screens)}",
        "",
    ]

    for layer in layers:
        context_parts.append(f"### Layer: {layer.name}")
        context_parts.append(f"- Layer ID: {layer.node_id}")
        context_parts.append(f"- Type: {layer.type}")
        context_parts.append("")

        layer_screens = [
            screen for screen in screens
            if screen.layer_id == layer.node_id
        ]

        if not layer_screens:
            context_parts.append("- [NO SCREENS FOUND IN THIS LAYER]")
            context_parts.append("")
            continue

        for screen in layer_screens:
            layer_dir = (
                output_root
                / "layers"
                / _safe_name(layer.node_id)
            )
            screen_dir = (
                layer_dir
                / "screens"
                / _safe_name(screen.node_id)
            )
            screen_dir.mkdir(parents=True, exist_ok=True)

            screen_document = screen_documents.get(screen.node_id) or {}

            if screen_document:
                _write_json_compact(
                    screen_dir / "screen_node.json",
                    screen_document,
                )

            image_file = None
            frame_file = screen_dir / "frame.png"
            image_export_status = "not_attempted"
            vision_analysis_status = "not_attempted"
            local_vision_enabled = is_figma_local_vision_enabled()
            image_url = image_urls.get(screen.node_id)

            if not image_export_enabled:
                if frame_file.exists():
                    image_file = frame_file
                    image_export_status = "existing_export_disabled"
                    _remove_file_if_exists(screen_dir / "image_export_skipped.txt")
                else:
                    image_export_status = "skipped_disabled"
                    (screen_dir / "image_export_skipped.txt").write_text(
                        FIGMA_IMAGE_EXPORT_SKIPPED_MESSAGE,
                        encoding="utf-8",
                    )
            elif image_url:
                try:
                    download_image(
                        image_url=image_url,
                        output_file=frame_file,
                    )
                    image_file = frame_file
                    image_export_status = "exported"
                    _remove_file_if_exists(screen_dir / "image_export_skipped.txt")
                    _remove_file_if_exists(screen_dir / "image_download_error.txt")
                except Exception as error:
                    if frame_file.exists():
                        image_file = frame_file
                        image_export_status = "existing_download_error"
                        _remove_file_if_exists(
                            screen_dir / "image_export_skipped.txt"
                        )
                    else:
                        image_export_status = "download_error"
                        (screen_dir / "image_export_skipped.txt").write_text(
                            FIGMA_IMAGE_EXPORT_SKIPPED_MESSAGE,
                            encoding="utf-8",
                        )

                    (screen_dir / "image_download_error.txt").write_text(
                        "".join(
                            traceback.format_exception(
                                type(error),
                                error,
                                error.__traceback__,
                            )
                        ),
                        encoding="utf-8",
                    )
            else:
                if frame_file.exists():
                    image_file = frame_file
                    image_export_status = "existing_no_url"
                    _remove_file_if_exists(screen_dir / "image_export_skipped.txt")
                else:
                    image_export_status = "skipped_no_url"
                    (screen_dir / "image_export_skipped.txt").write_text(
                        FIGMA_IMAGE_EXPORT_SKIPPED_MESSAGE,
                        encoding="utf-8",
                    )

            vision_analysis = None

            if image_file and local_vision_enabled:
                try:
                    _remove_file_if_exists(screen_dir / "vision_analysis_skipped.txt")
                    _remove_file_if_exists(screen_dir / "vision_analysis.md")
                    vision_analysis = _analyze_with_local_vision(image_file)
                    vision_analysis_status = (
                        "analyzed" if vision_analysis else "empty"
                    )
                    _remove_file_if_exists(screen_dir / "vision_analysis_error.txt")
                except Exception as error:
                    vision_analysis_status = "error"
                    _remove_file_if_exists(screen_dir / "vision_analysis.md")
                    (screen_dir / "vision_analysis_error.txt").write_text(
                        "".join(
                            traceback.format_exception(
                                type(error),
                                error,
                                error.__traceback__,
                            )
                        ),
                        encoding="utf-8",
                    )
            elif image_file:
                vision_analysis_status = "skipped_disabled"
                _remove_file_if_exists(screen_dir / "vision_analysis.md")
                _remove_file_if_exists(screen_dir / "vision_analysis_error.txt")
                (screen_dir / "vision_analysis_skipped.txt").write_text(
                    VISION_ANALYSIS_SKIPPED_MESSAGE,
                    encoding="utf-8",
                )
            else:
                vision_analysis_status = "skipped_no_image"
                _remove_file_if_exists(screen_dir / "vision_analysis.md")
                _remove_file_if_exists(screen_dir / "vision_analysis_error.txt")
                _remove_file_if_exists(screen_dir / "vision_analysis_skipped.txt")

            if vision_analysis:
                (screen_dir / "vision_analysis.md").write_text(
                    vision_analysis,
                    encoding="utf-8",
                )

            print(
                "Figma screen export status: "
                f"ticket_id={ticket_id}, page_id={page_scope.page_id}, "
                f"screen_id={screen.node_id}, "
                f"image_export_enabled={image_export_enabled}, "
                f"image_export_status={image_export_status}, "
                f"local_vision_enabled={local_vision_enabled}, "
                f"vision_analysis_status={vision_analysis_status}"
            )

            screen_context = _build_screen_context(
                screen=screen,
                screen_document=screen_document,
                image_file=image_file,
                vision_analysis=vision_analysis,
            )

            (screen_dir / "screen_context.md").write_text(
                screen_context,
                encoding="utf-8",
            )

            context_parts.append(screen_context)
            context_parts.append("\n---\n")

            time.sleep(0.1)

    final_context = "\n".join(context_parts).strip()

    (output_root / "figma_page_context.md").write_text(
        final_context,
        encoding="utf-8",
    )

    return final_context


def export_figma_file_from_reference(
    ticket_id: str,
    reference: FigmaFileReference,
) -> str:
    extract_scope = _env_str("FIGMA_EXTRACT_SCOPE", "linked_page").lower()

    if extract_scope not in {"linked_page", "linked_node", "file"}:
        extract_scope = "linked_page"

    if extract_scope != "linked_page":
        raise RuntimeError(
            f"FIGMA_EXTRACT_SCOPE={extract_scope} is not supported in this implementation. "
            "Use FIGMA_EXTRACT_SCOPE=linked_page."
        )

    page_scopes = resolve_target_pages(
        file_key=reference.file_key,
        entry_node_ids=reference.entry_node_ids,
    )
    page_scopes = _dedupe_page_scopes(
        reference=reference,
        page_scopes=page_scopes,
    )

    context_parts = [
        "# Figma File Context",
        "",
        f"- File key: {reference.file_key}",
        "- Source URLs:",
        *[f"  - {url}" for url in reference.source_urls],
        "",
        f"- Resolved target pages: {len(page_scopes)}",
        "",
    ]

    file_root = (
        REQUIREMENTS_ROOT
        / ticket_id
        / "source"
        / "figma"
        / _safe_name(reference.file_key)
    )
    file_root.mkdir(parents=True, exist_ok=True)

    _write_json_pretty(
        file_root / "file_reference.json",
        {
            **asdict(reference),
            "resolved_pages": [
                {
                    "file_key": page_scope.file_key,
                    "page_id": page_scope.page_id,
                    "page_name": page_scope.page_name,
                    "source_links": page_scope.source_links,
                    "entry_node_ids": page_scope.entry_node_ids,
                    "duplicate_link_count": page_scope.duplicate_link_count,
                    "skipped_duplicate_pages": page_scope.skipped_duplicate_pages,
                }
                for page_scope in page_scopes
            ],
            "dedupe_key": ["file_key", "page_id"],
        },
    )

    for page_scope in page_scopes:
        context = export_figma_page_scope(
            ticket_id=ticket_id,
            reference=reference,
            page_scope=page_scope,
        )
        context_parts.append(context)
        context_parts.append("\n---\n")

    final_context = "\n".join(context_parts).strip()

    (file_root / "figma_file_context.md").write_text(
        final_context,
        encoding="utf-8",
    )

    return final_context


def extract_figma_context_from_jira_texts(
    ticket_id: str,
    texts: list[str],
) -> str:
    if not _env_bool("FIGMA_ENABLE_EXTRACTION", False):
        return ""

    references = extract_figma_references_from_texts(texts)

    if not references:
        return ""

    max_files = _env_int("FIGMA_MAX_FILES_PER_TICKET", 5)
    references = references[:max_files]

    figma_root = REQUIREMENTS_ROOT / ticket_id / "source" / "figma"
    figma_root.mkdir(parents=True, exist_ok=True)

    _write_json_pretty(
        figma_root / "figma_links.json",
        [asdict(item) for item in references],
    )

    context_parts = ["# Figma Context", ""]

    for reference in references:
        try:
            context = export_figma_file_from_reference(
                ticket_id=ticket_id,
                reference=reference,
            )
            context_parts.append(context)

        except Exception as error:
            error_text = "".join(
                traceback.format_exception(
                    type(error),
                    error,
                    error.__traceback__,
                )
            )

            context_parts.append(
                f"## Figma extraction error\n\n"
                f"- File key: {reference.file_key}\n"
                f"- Error type: {type(error).__name__}\n"
                f"- Error repr: {repr(error)}\n\n"
                f"```text\n{error_text}\n```\n"
            )

            error_log_file = (
                REQUIREMENTS_ROOT
                / ticket_id
                / "logs"
                / "figma_extraction_errors.txt"
            )
            error_log_file.parent.mkdir(parents=True, exist_ok=True)
            error_log_file.write_text(
                error_text,
                encoding="utf-8",
            )

    final_context = "\n\n".join(context_parts).strip()

    (figma_root / "figma_requirement_context.md").write_text(
        final_context,
        encoding="utf-8",
    )

    return final_context
