import json
import os
import re
import time
import traceback
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


REQUIREMENTS_ROOT = Path("requirements")
FIGMA_API_BASE_URL = "https://api.figma.com/v1"


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

    pattern = re.compile(
        r"https://(?:www\.)?figma\.com/(?:design|file|proto)/[^\s\]\)\}<>\"']+",
        flags=re.IGNORECASE,
    )

    urls: list[str] = []

    for match in pattern.findall(text):
        url = match.rstrip(".,;")
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
    name = node.get("name", "")
    width, height = _extract_size(node)

    if not node_id:
        return False

    if node_type not in {
        "FRAME",
        "SECTION",
        "GROUP",
        "COMPONENT",
        "COMPONENT_SET",
        "INSTANCE",
    }:
        return False

    # Layer/container can be very large, so do not use screen-size filter here.
    # Only skip obviously tiny/invalid nodes when bounding box is available.
    if width > 0 and height > 0:
        if not _is_reasonable_layer_size(width, height):
            return False

    # Do not apply aggressive blacklist to layer level.
    # Some real layers may include words like background/state/container.
    if _should_skip_layer_by_name(name):
        return False

    return True


def _is_screen_candidate(node: dict[str, Any]) -> bool:
    node_type = node.get("type", "")
    node_id = node.get("id", "")
    name = node.get("name", "")
    width, height = _extract_size(node)

    return (
        bool(node_id)
        and node_type in {"FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE"}
        and _is_reasonable_size(width, height)
        and not _should_skip_node_by_name(name)
    )
    
    
def _explain_layer_candidate(node: dict[str, Any]) -> str:
    node_type = node.get("type", "")
    node_id = node.get("id", "")
    name = node.get("name", "")
    width, height = _extract_size(node)

    if not node_id:
        return "missing node id"

    if node_type not in {
        "FRAME",
        "SECTION",
        "GROUP",
        "COMPONENT",
        "COMPONENT_SET",
        "INSTANCE",
    }:
        return f"unsupported type: {node_type}"

    if width > 0 and height > 0 and not _is_reasonable_layer_size(width, height):
        return f"layer size filtered: {width}x{height}"

    if _should_skip_layer_by_name(name):
        return f"layer name blacklisted: {name}"

    return "accepted"


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

            # Do not return here. Continue walking because visual "layers"
            # may be nested under a wrapper frame/group.
        
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

    max_layers = _env_int("FIGMA_MAX_LAYERS_PER_PAGE", 30)

    return deduped[:max_layers]


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

    if not screens and _env_bool("FIGMA_EXPORT_CONTAINER_LAYERS", False):
        if _is_screen_candidate(layer_document):
            width, height = _extract_size(layer_document)
            text_count = _count_text_descendants(layer_document)

            screens.append(
                FigmaScreenRef(
                    node_id=layer_ref.node_id,
                    name=layer_ref.name,
                    type=layer_ref.type,
                    page_id=page_scope.page_id,
                    page_name=page_scope.page_name,
                    layer_id=layer_ref.node_id,
                    layer_name=layer_ref.name,
                    width=width,
                    height=height,
                    text_count=text_count,
                )
            )

    max_screens_per_layer = _env_int("FIGMA_MAX_SCREENS_PER_LAYER", 50)

    screens.sort(
        key=lambda item: (
            item.text_count,
            item.width * item.height,
        ),
        reverse=True,
    )

    return screens[:max_screens_per_layer]


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
        page_children_debug.append(
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "type": child.get("type"),
                "size": _extract_size(child),
                "candidate_reason": _explain_layer_candidate(child),
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

    layers = collect_layers_from_page(
        page_scope=page_scope,
        page_document=page_document,
    )
    
    if not layers:
        page_width, page_height = _extract_size(page_document)

        layers = [
            FigmaLayerRef(
                node_id=page_scope.page_id,
                name=page_scope.page_name or "Target Page",
                type=page_document.get("type", "CANVAS"),
                page_id=page_scope.page_id,
                page_name=page_scope.page_name,
                width=page_width,
                height=page_height,
            )
        ]

    all_screens: list[FigmaScreenRef] = []
    screen_documents: dict[str, dict[str, Any]] = {}

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
            continue

        layer_document = layer_payload.get("document") or {}

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

        for screen in screens:
            if screen.node_id not in screen_documents:
                all_screens.append(screen)

                screen_documents[screen.node_id] = _find_node_by_id(
                    layer_document,
                    screen.node_id,
                ) or {}

        time.sleep(0.1)

    max_screens_per_page = _env_int("FIGMA_MAX_SCREENS_PER_PAGE", 100)

    all_screens = all_screens[:max_screens_per_page]

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
            images = _get_figma_image_urls_once(
                file_key=file_key,
                node_ids=batch,
                scale=export_scale,
            )
            all_images.update(images)

        except RuntimeError as error:
            error_text = str(error)

            if (
                "Render timeout" not in error_text
                and "try requesting fewer" not in error_text
            ):
                raise

            for node_id in batch:
                try:
                    images = _get_figma_image_urls_once(
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


def _analyze_with_qwen_if_enabled(
    image_file: Path | None,
) -> str | None:
    if not image_file:
        return None

    if not _env_bool("FIGMA_ANALYZE_WITH_QWEN", False):
        return None

    try:
        from app.services.gemma_image_extractor_service import extract_image_with_gemma

        return extract_image_with_gemma(
            image_path=image_file,
            prompt=FIGMA_IMAGE_ANALYSIS_PROMPT,
        )

    except Exception as error:
        return (
            "Vision analysis failed.\n\n"
            f"```text\n"
            f"{''.join(traceback.format_exception(type(error), error, error.__traceback__))}"
            f"\n```"
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
        "source_urls": reference.source_urls,
        "page_id": page_scope.page_id,
        "page_name": page_scope.page_name,
        "entry_node_ids": page_scope.entry_node_ids,
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

    try:
        image_urls = get_figma_image_urls(
            file_key=reference.file_key,
            node_ids=screen_ids,
        )
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
        *[f"  - {url}" for url in reference.source_urls],
        "",
        "- Entry node IDs:",
        *[f"  - {node_id}" for node_id in page_scope.entry_node_ids],
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
            image_url = image_urls.get(screen.node_id)

            if image_url:
                try:
                    image_file = screen_dir / "frame.png"
                    download_image(
                        image_url=image_url,
                        output_file=image_file,
                    )
                except Exception as error:
                    image_file = None
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
                (screen_dir / "image_export_skipped.txt").write_text(
                    "Figma image export skipped or unavailable for this screen.",
                    encoding="utf-8",
                )

            vision_analysis = _analyze_with_qwen_if_enabled(image_file)

            if vision_analysis:
                (screen_dir / "vision_analysis.md").write_text(
                    vision_analysis,
                    encoding="utf-8",
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
        asdict(reference),
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