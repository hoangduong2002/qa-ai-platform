import json
import os
import re
from pathlib import Path
from typing import Any


REQUIREMENTS_ROOT = Path("requirements")
DEFAULT_MAX_CONTEXT_CHARS = 60_000
DEFAULT_CHUNK_MAX_CHARS = 20_000
DEFAULT_MAX_TEXT_ITEMS_PER_SCREEN = 10
DEFAULT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN = 50
TRUNCATION_NOTE = "[TRUNCATED BY REQUIREMENT_COMPACT_CONTEXT_MAX_CHARS]"
FIGMA_ONLY_WARNING = (
    "Jira/source markdown not found. "
    "This appears to be a Figma-only compact context."
)


SKIP_NAME_PARTS = {
    "debug",
    "log",
    "logs",
    "traceback",
    "error",
    "raw",
    "target_page",
    "page_children_debug",
    "layer_screen_debug",
    "flow_connectors_debug",
    "screen_node",
    "layer.json",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _safe_read_text(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as error:
        warnings.append(f"Could not read {path}: {error}")
        return ""


def _safe_read_json(path: Path, warnings: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as error:
        warnings.append(f"Could not parse JSON {path}: {error}")
        return None


def _write_json_pretty(output_file: Path, payload: Any) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(output_file: Path, payload: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(payload, encoding="utf-8")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _is_skipped_source_file(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    lowered_name = path.name.lower()

    if lowered_name in {"screen_context.md", "vision_analysis.md"}:
        return True

    if "figma" in lowered_parts:
        return True

    if lowered_name.endswith(".json"):
        return True

    return any(skip in lowered_parts or skip in lowered_name for skip in SKIP_NAME_PARTS)


def _collect_source_text_files(source_root: Path) -> list[Path]:
    preferred = [
        source_root / "jira_requirement.md",
        source_root / "sanitized_requirement.md",
    ]
    files: list[Path] = [path for path in preferred if path.exists()]

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue

        if path.suffix.lower() not in {".md", ".txt"}:
            continue

        if path in files or _is_skipped_source_file(path):
            continue

        files.append(path)

    return files


def _compact_source_excerpt(text: str, max_chars: int = 8_000) -> str:
    text = text.strip()

    if len(text) <= max_chars:
        return text

    head_chars = max_chars * 2 // 3
    tail_chars = max_chars - head_chars
    return (
        text[:head_chars].rstrip()
        + "\n\n[RAW SOURCE TRUNCATED IN COMPACT CONTEXT]\n\n"
        + text[-tail_chars:].lstrip()
    )


def _clean_list_item(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^[-*]\s+", "", value)
    value = re.sub(r"^\d+[.)]\s+", "", value)
    return value.strip()


def _is_empty_marker(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized in {"[no text layers or not fetched]", "[not available]"}
        or normalized.startswith("[no ")
        or normalized.startswith("[unreadable]")
    )


def _unique_append(items: list[str], value: str, max_items: int = 80) -> None:
    value = _clean_list_item(value)

    if _is_empty_marker(value):
        return

    if value not in items and len(items) < max_items:
        items.append(value)


def _extract_markdown_list_after_headings(
    text: str,
    headings: set[str],
    max_items: int = 80,
) -> list[str]:
    items: list[str] = []
    active = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)

        if heading_match:
            heading = heading_match.group(1).strip().lower()
            active = heading in headings
            continue

        if not active:
            continue

        if line.startswith(("-", "*")) or re.match(r"^\d+[.)]\s+", line):
            _unique_append(items, line, max_items=max_items)

    return items


def _extract_ticket_summary(source_texts: list[tuple[Path, str]]) -> str:
    for _, text in source_texts:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("#"):
                line = line.lstrip("#").strip()

            if line:
                return line[:500]

    return "No ticket summary source was found."


def _extract_open_questions(source_texts: list[tuple[Path, str]]) -> list[str]:
    questions: list[str] = []

    for _, text in source_texts:
        for line in text.splitlines():
            cleaned = _clean_list_item(line)
            lowered = cleaned.lower()

            if "?" in cleaned or "clarification" in lowered or "unclear" in lowered:
                _unique_append(questions, cleaned, max_items=30)

    return questions


def _extract_explicit_rules(source_texts: list[tuple[Path, str]]) -> list[str]:
    rules: list[str] = []
    keywords = [
        "must",
        "shall",
        "should",
        "required",
        "mandatory",
        "validate",
        "validation",
        "error",
        "business rule",
        "acceptance criteria",
    ]

    for _, text in source_texts:
        for line in text.splitlines():
            cleaned = _clean_list_item(line)
            lowered = cleaned.lower()

            if any(keyword in lowered for keyword in keywords):
                _unique_append(rules, cleaned, max_items=60)

    return rules


def _safe_name(value: str, fallback: str = "chunk") -> str:
    value = (value or fallback).strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:80] or fallback


def _limit_items(items: list[str], max_items: int) -> list[str]:
    limited: list[str] = []

    for item in items:
        _unique_append(limited, str(item), max_items=max_items)

    return limited


def _append_limited_list(
    lines: list[str],
    items: list[str],
    empty_message: str,
    max_items: int,
) -> None:
    limited = _limit_items(items, max_items)

    if limited:
        lines.extend(f"- {item}" for item in limited)
    else:
        lines.append(f"- {empty_message}")


def _classify_source_file(path: Path) -> str:
    lowered_parts = [part.lower() for part in path.parts]
    lowered_name = path.name.lower()
    lowered_path = str(path).lower()

    if "attachment" in lowered_path or "attachments" in lowered_parts:
        return "attachments"

    if "comment" in lowered_name or "comments" in lowered_parts:
        return "jira_comments"

    if lowered_name in {
        "jira_requirement.md",
        "sanitized_requirement.md",
        "description.md",
    }:
        return "jira_core"

    if "jira" in lowered_parts:
        return "jira_core"

    return "generic_source"


def _split_text_into_parts(text: str, max_chars: int) -> list[str]:
    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        extra_len = len(paragraph) + 2

        if current and current_len + extra_len > max_chars:
            parts.append("\n\n".join(current).strip())
            current = []
            current_len = 0

        if len(paragraph) > max_chars:
            for index in range(0, len(paragraph), max_chars):
                part = paragraph[index:index + max_chars].strip()
                if part:
                    parts.append(part)
            continue

        current.append(paragraph)
        current_len += extra_len

    if current:
        parts.append("\n\n".join(current).strip())

    return parts


def _group_screens_by_section(
    screens: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}

    for screen in screens:
        key = (
            screen.get("page_id", ""),
            screen.get("page_name", ""),
            screen.get("section_id", ""),
            screen.get("section_name", ""),
        )
        grouped.setdefault(key, []).append(screen)

    return grouped


def _render_source_chunk(
    ticket_id: str,
    chunk_type: str,
    source_items: list[tuple[Path, str]],
) -> str:
    title = chunk_type.replace("_", " ").title()
    lines = [
        f"# Requirement Chunk: {title}",
        "",
        f"- Ticket: {ticket_id}",
        f"- Chunk type: {chunk_type}",
        f"- Source files: {len(source_items)}",
    ]

    for path, text in source_items:
        lines.extend(
            [
                "",
                f"## Source: {_relative(path)}",
                text.strip() or "[EMPTY SOURCE]",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _render_figma_section_chunk(
    ticket_id: str,
    section_key: tuple[str, str, str, str],
    screens: list[dict[str, Any]],
) -> str:
    page_id, page_name, section_id, section_name = section_key
    max_items = _env_int(
        "REQUIREMENT_COMPACT_MAX_TEXT_ITEMS_PER_SCREEN",
        DEFAULT_MAX_TEXT_ITEMS_PER_SCREEN,
    )
    lines = [
        f"# Requirement Chunk: Figma Section - {section_name or '[UNNAMED SECTION]'}",
        "",
        f"- Ticket: {ticket_id}",
        "- Chunk type: figma_section",
        f"- Page: {page_name or '[UNKNOWN PAGE]'} ({page_id or '[NO PAGE ID]'})",
        f"- Section: {section_name or '[UNNAMED SECTION]'} ({section_id or '[NO SECTION ID]'})",
        f"- Screens in chunk: {len(screens)}",
    ]

    for screen in screens:
        lines.extend(
            [
                "",
                f"## Screen: {screen.get('screen_name') or '[UNNAMED SCREEN]'}",
                f"- Screen ID: {screen.get('screen_id')}",
                f"- Image: {screen.get('image_path') or '[NOT AVAILABLE]'}",
                "",
                "### Visible UI Text",
            ]
        )
        _append_limited_list(
            lines,
            screen.get("visible_text") or [],
            "[NO VISIBLE TEXT EXTRACTED]",
            max_items,
        )

        lines.append("")
        lines.append("### UI Elements")
        _append_limited_list(
            lines,
            screen.get("ui_elements") or [],
            "[NO UI ELEMENTS EXTRACTED]",
            max_items,
        )

        lines.append("")
        lines.append("### Possible Actions")
        _append_limited_list(
            lines,
            screen.get("possible_actions") or [],
            "[NO ACTIONS EXTRACTED]",
            max_items,
        )

        qa_notes = screen.get("qa_notes") or []
        if qa_notes:
            lines.append("")
            lines.append("### QA Notes")
            _append_limited_list(lines, qa_notes, "[NO QA NOTES]", max_items)

    return "\n".join(lines).strip() + "\n"


def _summarize_source_chunk(
    chunk_type: str,
    source_items: list[tuple[Path, str]],
) -> str:
    title = chunk_type.replace("_", " ").title()
    source_texts = source_items
    summary = _extract_ticket_summary(source_texts)
    rules = _extract_explicit_rules(source_texts)
    questions = _extract_open_questions(source_texts)

    lines = [
        f"# Partial Summary: {title}",
        "",
        f"- Chunk type: {chunk_type}",
        f"- Source files: {len(source_items)}",
        "",
        "## Summary",
        summary,
        "",
        "## Functional / Explicit Requirement Signals",
    ]
    _append_limited_list(lines, rules, "[NO EXPLICIT REQUIREMENT SIGNALS FOUND]", 25)

    lines.extend(["", "## Open Questions"])
    _append_limited_list(lines, questions, "[NO OPEN QUESTIONS DETECTED]", 15)

    lines.extend(["", "## Source Traceability"])
    lines.extend(f"- {_relative(path)}" for path, _ in source_items)

    return "\n".join(lines).strip() + "\n"


def _summarize_figma_section_chunk(
    section_key: tuple[str, str, str, str],
    screens: list[dict[str, Any]],
) -> str:
    page_id, page_name, section_id, section_name = section_key
    visible_text: list[str] = []
    ui_elements: list[str] = []
    actions: list[str] = []
    qa_notes: list[str] = []

    for screen in screens:
        for item in screen.get("visible_text") or []:
            _unique_append(visible_text, item, max_items=80)
        for item in screen.get("ui_elements") or []:
            _unique_append(ui_elements, item, max_items=80)
        for item in screen.get("possible_actions") or []:
            _unique_append(actions, item, max_items=60)
        for item in screen.get("qa_notes") or []:
            _unique_append(qa_notes, item, max_items=40)

    max_screens = _env_int(
        "REQUIREMENT_COMPACT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN",
        DEFAULT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN,
    )
    listed_screens = screens[:max_screens]

    lines = [
        f"# Partial Summary: Figma Section - {section_name or '[UNNAMED SECTION]'}",
        "",
        "- Chunk type: figma_section",
        f"- Page: {page_name or '[UNKNOWN PAGE]'} ({page_id or '[NO PAGE ID]'})",
        f"- Section: {section_name or '[UNNAMED SECTION]'} ({section_id or '[NO SECTION ID]'})",
        f"- Screens summarized: {len(screens)}",
        "",
        "## Screens",
    ]

    for screen in listed_screens:
        lines.append(
            "- "
            f"{screen.get('screen_name') or '[UNNAMED SCREEN]'} "
            f"({screen.get('screen_id')})"
        )

    if len(screens) > len(listed_screens):
        lines.append(f"- [... {len(screens) - len(listed_screens)} more screens omitted]")

    lines.extend(["", "## Key Visible Texts / States"])
    _append_limited_list(lines, visible_text, "[NO VISIBLE TEXT EXTRACTED]", 40)

    lines.extend(["", "## UI Elements"])
    _append_limited_list(lines, ui_elements, "[NO UI ELEMENTS EXTRACTED]", 35)

    lines.extend(["", "## Possible Actions"])
    _append_limited_list(lines, actions, "[NO ACTIONS EXTRACTED]", 25)

    if qa_notes:
        lines.extend(["", "## QA Notes"])
        _append_limited_list(lines, qa_notes, "[NO QA NOTES]", 25)

    return "\n".join(lines).strip() + "\n"


def _cleanup_chunk_folder(chunks_root: Path) -> None:
    chunks_root.mkdir(parents=True, exist_ok=True)

    for path in chunks_root.iterdir():
        if path.is_file() and (
            path.name.startswith("chunk_")
            or path.name.startswith("partial_")
            or path.name == "chunks_index.json"
        ):
            path.unlink()


def _write_chunk_and_partial(
    chunks_root: Path,
    index: int,
    chunk_type: str,
    safe_suffix: str,
    chunk_text: str,
    partial_text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    name_part = chunk_type if safe_suffix == chunk_type else f"{chunk_type}_{safe_suffix}"
    chunk_file = chunks_root / f"chunk_{index:03d}_{name_part}.md"
    partial_file = chunks_root / f"partial_{index:03d}_{name_part}.md"

    _write_text(chunk_file, chunk_text)
    _write_text(partial_file, partial_text)

    return {
        "index": index,
        "type": chunk_type,
        "chunk_path": _relative(chunk_file),
        "partial_summary_path": _relative(partial_file),
        "chunk_char_count": len(chunk_text),
        "partial_summary_char_count": len(partial_text),
        **metadata,
    }


def build_requirement_chunks(ticket_id: str) -> list[dict]:
    source_root = REQUIREMENTS_ROOT / ticket_id / "source"
    analysis_root = REQUIREMENTS_ROOT / ticket_id / "analysis"
    chunks_root = analysis_root / "compact_chunks"
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    chunk_max_chars = _env_int("REQUIREMENT_CHUNK_MAX_CHARS", DEFAULT_CHUNK_MAX_CHARS)

    _cleanup_chunk_folder(chunks_root)

    if not source_root.exists():
        _write_json_pretty(chunks_root / "chunks_index.json", [])
        return []

    source_files = _collect_source_text_files(source_root)
    source_texts = [
        (path, _safe_read_text(path, warnings))
        for path in source_files
    ]

    source_groups: dict[str, list[tuple[Path, str]]] = {
        "jira_core": [],
        "jira_comments": [],
        "attachments": [],
        "generic_source": [],
    }

    for path, text in source_texts:
        source_groups.setdefault(_classify_source_file(path), []).append((path, text))

    next_index = 1

    for chunk_type in ["jira_core", "jira_comments", "attachments", "generic_source"]:
        items = source_groups.get(chunk_type) or []
        if not items:
            continue

        combined_text = "\n\n".join(
            f"## Source: {_relative(path)}\n\n{text.strip()}"
            for path, text in items
            if text.strip()
        ).strip()
        parts = _split_text_into_parts(combined_text, chunk_max_chars)

        for part_index, part in enumerate(parts, start=1):
            part_items = [(Path(f"{chunk_type}_part_{part_index}.md"), part)]
            chunk_text = _render_source_chunk(
                ticket_id=ticket_id,
                chunk_type=chunk_type,
                source_items=part_items,
            )
            partial_text = _summarize_source_chunk(
                chunk_type=chunk_type,
                source_items=items if len(parts) == 1 else part_items,
            )
            suffix = _safe_name(
                chunk_type if len(parts) == 1 else f"{chunk_type}_{part_index}"
            )
            chunks.append(
                _write_chunk_and_partial(
                    chunks_root=chunks_root,
                    index=next_index,
                    chunk_type=chunk_type,
                    safe_suffix=suffix,
                    chunk_text=chunk_text,
                    partial_text=partial_text,
                    metadata={
                        "source_files": [_relative(path) for path, _ in items],
                    },
                )
            )
            next_index += 1

    screens, _ = _load_figma_screens(source_root, warnings)
    grouped_screens = _group_screens_by_section(screens)

    for section_key, section_screens in sorted(
        grouped_screens.items(),
        key=lambda item: (item[0][1], item[0][3], item[0][2]),
    ):
        page_id, page_name, section_id, section_name = section_key
        chunk_text = _render_figma_section_chunk(
            ticket_id=ticket_id,
            section_key=section_key,
            screens=section_screens,
        )

        screen_batches = [section_screens]
        if len(chunk_text) > chunk_max_chars:
            screen_batches = [
                section_screens[index:index + 20]
                for index in range(0, len(section_screens), 20)
            ]

        for batch_index, screen_batch in enumerate(screen_batches, start=1):
            batch_section_name = section_name
            suffix_source = section_name or section_id or f"section_{next_index}"

            if len(screen_batches) > 1:
                suffix_source = f"{suffix_source}_{batch_index}"

            chunk_text = _render_figma_section_chunk(
                ticket_id=ticket_id,
                section_key=section_key,
                screens=screen_batch,
            )
            partial_text = _summarize_figma_section_chunk(
                section_key=section_key,
                screens=screen_batch,
            )
            chunks.append(
                _write_chunk_and_partial(
                    chunks_root=chunks_root,
                    index=next_index,
                    chunk_type="figma_section",
                    safe_suffix=_safe_name(suffix_source, "figma_section"),
                    chunk_text=chunk_text,
                    partial_text=partial_text,
                    metadata={
                        "page_id": page_id,
                        "page_name": page_name,
                        "section_id": section_id,
                        "section_name": batch_section_name,
                        "screen_count": len(screen_batch),
                    },
                )
            )
            next_index += 1

    _write_json_pretty(chunks_root / "chunks_index.json", chunks)
    return chunks


def _find_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path

    return None


def _safe_node_dir_name(node_id: str) -> str:
    return (node_id or "unknown").replace(":", "_")


def _index_paths_by_screen_id(paths: list[Path]) -> dict[str, Path]:
    indexed: dict[str, Path] = {}

    for path in paths:
        screen_id = path.parent.name.replace("_", ":")
        indexed.setdefault(screen_id, path)

    return indexed


def _parse_screen_context(
    screen_context: str,
    vision_analysis: str,
) -> dict[str, list[str]]:
    combined = "\n\n".join(part for part in [screen_context, vision_analysis] if part)

    visible_text = _extract_markdown_list_after_headings(
        combined,
        {"figma text layers", "visible ui text"},
        max_items=100,
    )
    ui_elements = _extract_markdown_list_after_headings(
        combined,
        {"ui elements", "layout / screen structure"},
        max_items=80,
    )
    possible_actions = _extract_markdown_list_after_headings(
        combined,
        {"possible user actions"},
        max_items=60,
    )
    qa_notes = _extract_markdown_list_after_headings(
        combined,
        {"potential qa notes", "validation/business rules", "validation and business rules"},
        max_items=60,
    )

    return {
        "visible_text": visible_text,
        "ui_elements": ui_elements,
        "possible_actions": possible_actions,
        "qa_notes": qa_notes,
    }


def _load_figma_layers(source_root: Path, warnings: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    layers: list[dict[str, Any]] = []
    figma_files: list[str] = []

    for path in sorted(source_root.glob("figma/**/extracted_layers.json")):
        data = _safe_read_json(path, warnings)
        figma_files.append(_relative(path))

        if not isinstance(data, list):
            warnings.append(f"Expected list in {path}")
            continue

        for layer in data:
            if isinstance(layer, dict):
                item = dict(layer)
                item["source_path"] = _relative(path)
                layers.append(item)

    return layers, figma_files


def _load_figma_screens(
    source_root: Path,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    screens: list[dict[str, Any]] = []
    figma_files: list[str] = []

    screen_context_paths = _index_paths_by_screen_id(
        sorted(source_root.glob("figma/**/screen_context.md"))
    )
    vision_paths = _index_paths_by_screen_id(
        sorted(source_root.glob("figma/**/vision_analysis.md"))
    )

    for path in sorted(source_root.glob("figma/**/extracted_screens.json")):
        data = _safe_read_json(path, warnings)
        figma_files.append(_relative(path))

        if not isinstance(data, list):
            warnings.append(f"Expected list in {path}")
            continue

        page_root = path.parent

        for screen in data:
            if not isinstance(screen, dict):
                continue

            screen_id = screen.get("node_id", "")
            section_id = screen.get("layer_id", "")
            screen_dir = (
                page_root
                / "layers"
                / _safe_node_dir_name(section_id)
                / "screens"
                / _safe_node_dir_name(screen_id)
            )
            screen_context_path = _find_first_existing(
                [
                    screen_dir / "screen_context.md",
                    screen_context_paths.get(screen_id) or Path("__missing__"),
                ]
            )
            vision_analysis_path = _find_first_existing(
                [
                    screen_dir / "vision_analysis.md",
                    vision_paths.get(screen_id) or Path("__missing__"),
                ]
            )
            image_path = _find_first_existing([screen_dir / "frame.png"])
            vision_skipped_path = _find_first_existing(
                [screen_dir / "vision_analysis_skipped.txt"]
            )

            screen_context = (
                _safe_read_text(screen_context_path, warnings)
                if screen_context_path
                else ""
            )
            vision_analysis = (
                _safe_read_text(vision_analysis_path, warnings)
                if vision_analysis_path
                else ""
            )
            extracted = _parse_screen_context(
                screen_context=screen_context,
                vision_analysis=vision_analysis,
            )
            if image_path and vision_skipped_path and not vision_analysis_path:
                skipped_note = _safe_read_text(vision_skipped_path, warnings).strip()
                if skipped_note and skipped_note not in extracted["qa_notes"]:
                    extracted["qa_notes"].append(skipped_note)

            screens.append(
                {
                    "screen_id": screen_id,
                    "screen_name": screen.get("name", ""),
                    "section_id": section_id,
                    "section_name": screen.get("layer_name", ""),
                    "page_id": screen.get("page_id", ""),
                    "page_name": screen.get("page_name", ""),
                    "image_path": _relative(image_path) if image_path else "",
                    "screen_context_path": (
                        _relative(screen_context_path)
                        if screen_context_path
                        else ""
                    ),
                    "vision_analysis_path": (
                        _relative(vision_analysis_path)
                        if vision_analysis_path
                        else ""
                    ),
                    "visible_text": extracted["visible_text"],
                    "ui_elements": extracted["ui_elements"],
                    "possible_actions": extracted["possible_actions"],
                    "qa_notes": extracted["qa_notes"],
                }
            )

    return screens, figma_files


def _build_compact_markdown(
    ticket_id: str,
    source_texts: list[tuple[Path, str]],
    layers: list[dict[str, Any]],
    screens: list[dict[str, Any]],
    evidence_index: dict[str, Any],
) -> str:
    ticket_summary = _extract_ticket_summary(source_texts)
    explicit_rules = _extract_explicit_rules(source_texts)
    open_questions = _extract_open_questions(source_texts)

    lines: list[str] = [
        f"# Compact Requirement Context: {ticket_id}",
        "",
        "## Ticket Summary",
        ticket_summary,
        "",
        "## Functional Requirements From Sources",
    ]

    if source_texts:
        for path, text in source_texts:
            lines.extend(
                [
                    "",
                    f"### Source: {_relative(path)}",
                    _compact_source_excerpt(text),
                ]
            )
    else:
        lines.append("- [NO SOURCE MARKDOWN/TEXT FOUND]")

    lines.extend(["", "## Figma Pages And Sections"])

    if layers:
        for layer in layers:
            lines.append(
                "- "
                f"Page {layer.get('page_name') or '[UNKNOWN PAGE]'} "
                f"({layer.get('page_id') or '[NO PAGE ID]'}) / "
                f"Section {layer.get('name') or '[UNNAMED SECTION]'} "
                f"({layer.get('node_id') or '[NO SECTION ID]'})"
            )
    else:
        lines.append("- [NO FIGMA SECTIONS FOUND]")

    lines.extend(["", "## Screen List"])

    if screens:
        for index, screen in enumerate(screens, start=1):
            lines.append(
                "- "
                f"{index}. {screen.get('screen_name') or '[UNNAMED SCREEN]'} "
                f"({screen.get('screen_id')}) / "
                f"Section: {screen.get('section_name') or '[UNKNOWN SECTION]'}"
            )
    else:
        lines.append("- [NO FIGMA SCREENS FOUND]")

    lines.extend(["", "## Screen Evidence"])

    for screen in screens:
        lines.extend(
            [
                "",
                f"### Screen: {screen.get('screen_name') or '[UNNAMED SCREEN]'}",
                f"- Screen ID: {screen.get('screen_id')}",
                f"- Section: {screen.get('section_name')} ({screen.get('section_id')})",
                f"- Page: {screen.get('page_name')} ({screen.get('page_id')})",
                f"- Image: {screen.get('image_path') or '[NOT AVAILABLE]'}",
                f"- Source: {screen.get('screen_context_path') or '[NOT AVAILABLE]'}",
                "",
                "#### Visible UI Text",
            ]
        )

        visible_text = screen.get("visible_text") or []
        lines.extend([f"- {item}" for item in visible_text] or ["- [NO VISIBLE TEXT EXTRACTED]"])

        lines.append("")
        lines.append("#### UI Elements")
        ui_elements = screen.get("ui_elements") or []
        lines.extend([f"- {item}" for item in ui_elements] or ["- [NO UI ELEMENTS EXTRACTED]"])

        lines.append("")
        lines.append("#### Possible Actions")
        possible_actions = screen.get("possible_actions") or []
        lines.extend([f"- {item}" for item in possible_actions] or ["- [NO ACTIONS EXTRACTED]"])

        qa_notes = screen.get("qa_notes") or []

        if qa_notes:
            lines.append("")
            lines.append("#### QA Notes")
            lines.extend(f"- {item}" for item in qa_notes)

    lines.extend(["", "## Explicit Validation And Business Rules"])

    if explicit_rules:
        lines.extend(f"- {item}" for item in explicit_rules)
    else:
        lines.append("- [NO EXPLICIT VALIDATION OR BUSINESS RULES FOUND]")

    lines.extend(["", "## Open Questions And Ambiguities"])

    if open_questions:
        lines.extend(f"- {item}" for item in open_questions)
    else:
        lines.append("- [NO OPEN QUESTIONS DETECTED]")

    lines.extend(["", "## Source Traceability"])
    lines.append(f"- Source files indexed: {len(evidence_index.get('source_files') or [])}")
    lines.append(f"- Figma files indexed: {len(evidence_index.get('figma_files') or [])}")
    lines.append(f"- Section count: {evidence_index.get('section_count', 0)}")
    lines.append(f"- Screen count: {evidence_index.get('screen_count', 0)}")

    return "\n".join(lines).strip() + "\n"


def _read_partial_summaries(chunks: list[dict[str, Any]], warnings: list[str]) -> list[tuple[dict[str, Any], str]]:
    partials: list[tuple[dict[str, Any], str]] = []

    for chunk in chunks:
        path = Path(chunk.get("partial_summary_path") or "")
        if not path.exists():
            warnings.append(f"Missing partial summary file: {path}")
            continue

        partials.append((chunk, _safe_read_text(path, warnings)))

    return partials


def _build_merged_compact_markdown(
    ticket_id: str,
    source_texts: list[tuple[Path, str]],
    layers: list[dict[str, Any]],
    screens: list[dict[str, Any]],
    evidence_index: dict[str, Any],
    chunks: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    ticket_summary = _extract_ticket_summary(source_texts)
    explicit_rules = _extract_explicit_rules(source_texts)
    open_questions = _extract_open_questions(source_texts)
    partials = _read_partial_summaries(chunks, warnings)
    source_partials = [
        (chunk, text)
        for chunk, text in partials
        if chunk.get("type") in {"jira_core", "jira_comments", "attachments", "generic_source"}
    ]
    figma_partials = [
        (chunk, text)
        for chunk, text in partials
        if chunk.get("type") == "figma_section"
    ]
    grouped_screens = _group_screens_by_section(screens)

    lines: list[str] = [
        f"# Compact Requirement Context: {ticket_id}",
        "",
        "## Ticket Summary",
        ticket_summary,
        "",
        "## Functional Requirements",
    ]

    if source_partials:
        for chunk, text in source_partials:
            summary_lines = _extract_markdown_list_after_headings(
                text,
                {"functional / explicit requirement signals"},
                max_items=25,
            )
            if summary_lines:
                lines.append("")
                lines.append(f"### {str(chunk.get('type', '')).replace('_', ' ').title()}")
                lines.extend(f"- {item}" for item in summary_lines)
    elif source_texts:
        lines.append(_compact_source_excerpt("\n\n".join(text for _, text in source_texts), 4_000))
    else:
        lines.append("- [NO SOURCE MARKDOWN/TEXT FOUND]")

    lines.extend(["", "## Figma Sections Summary"])

    if layers:
        section_counts = {
            section_id: len(items)
            for (_, _, section_id, _), items in grouped_screens.items()
        }
        for layer in layers:
            section_id = layer.get("node_id", "")
            lines.append(
                "- "
                f"{layer.get('name') or '[UNNAMED SECTION]'} "
                f"({section_id or '[NO SECTION ID]'}) / "
                f"Page: {layer.get('page_name') or '[UNKNOWN PAGE]'} "
                f"/ Screens: {section_counts.get(section_id, 0)}"
            )
    else:
        lines.append("- [NO FIGMA SECTIONS FOUND]")

    lines.extend(["", "## Screens Grouped By Section"])

    if grouped_screens:
        max_screens = _env_int(
            "REQUIREMENT_COMPACT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN",
            DEFAULT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN,
        )
        for (_, page_name, section_id, section_name), section_screens in sorted(
            grouped_screens.items(),
            key=lambda item: (item[0][1], item[0][3], item[0][2]),
        ):
            lines.extend(
                [
                    "",
                    f"### {section_name or '[UNNAMED SECTION]'} ({section_id or '[NO SECTION ID]'})",
                    f"- Page: {page_name or '[UNKNOWN PAGE]'}",
                    f"- Screen count: {len(section_screens)}",
                ]
            )
            for screen in section_screens[:max_screens]:
                lines.append(
                    "- "
                    f"{screen.get('screen_name') or '[UNNAMED SCREEN]'} "
                    f"({screen.get('screen_id')})"
                )
            if len(section_screens) > max_screens:
                lines.append(f"- [... {len(section_screens) - max_screens} more screens omitted]")
    else:
        lines.append("- [NO FIGMA SCREENS FOUND]")

    lines.extend(["", "## Key Visible Texts / States"])
    visible_text: list[str] = []
    for screen in screens:
        for item in screen.get("visible_text") or []:
            _unique_append(visible_text, item, max_items=120)
    _append_limited_list(lines, visible_text, "[NO VISIBLE TEXT EXTRACTED]", 80)

    lines.extend(["", "## Possible Actions Summary"])
    actions: list[str] = []
    for screen in screens:
        for item in screen.get("possible_actions") or []:
            _unique_append(actions, item, max_items=80)
    _append_limited_list(lines, actions, "[NO ACTIONS EXTRACTED]", 50)

    lines.extend(["", "## Validation / Business Rules Explicit"])
    _append_limited_list(lines, explicit_rules, "[NO EXPLICIT VALIDATION OR BUSINESS RULES FOUND]", 60)

    figma_notes: list[str] = []
    for screen in screens:
        for item in screen.get("qa_notes") or []:
            _unique_append(figma_notes, item, max_items=40)

    if figma_notes:
        lines.extend(["", "## Figma QA Notes"])
        _append_limited_list(lines, figma_notes, "[NO FIGMA QA NOTES]", 40)

    lines.extend(["", "## Open Questions"])
    _append_limited_list(lines, open_questions, "[NO OPEN QUESTIONS DETECTED]", 30)

    lines.extend(["", "## Source Traceability Summary"])
    lines.append(f"- Source files indexed: {len(evidence_index.get('source_files') or [])}")
    lines.append(f"- Figma files indexed: {len(evidence_index.get('figma_files') or [])}")
    lines.append(f"- Chunk count: {len(chunks)}")
    lines.append(f"- Partial summaries: {len(partials)}")
    lines.append(f"- Section count: {evidence_index.get('section_count', 0)}")
    lines.append(f"- Screen count: {evidence_index.get('screen_count', 0)}")

    if chunks:
        lines.append("- Chunk index: analysis/compact_chunks/chunks_index.json")

    if figma_partials:
        lines.extend(["", "## Figma Partial Summary Sources"])
        for chunk, _ in figma_partials:
            lines.append(
                "- "
                f"{chunk.get('section_name') or '[UNNAMED SECTION]'}: "
                f"{chunk.get('partial_summary_path')}"
            )

    return "\n".join(lines).strip() + "\n"


def _truncate_context_if_needed(context: str, max_chars: int) -> tuple[str, bool]:
    if len(context) <= max_chars:
        return context, False

    note = f"\n\n{TRUNCATION_NOTE}\n"
    keep_chars = max(max_chars - len(note), 0)
    return context[:keep_chars].rstrip() + note, True


def _detect_compact_context_mode(source_files_count: int, screen_count: int) -> str:
    if source_files_count > 0 and screen_count > 0:
        return "JIRA_AND_FIGMA"

    if source_files_count > 0:
        return "JIRA_ONLY"

    if screen_count > 0:
        return "FIGMA_ONLY"

    return "EMPTY"


def build_compact_requirement_context(ticket_id: str) -> dict:
    source_root = REQUIREMENTS_ROOT / ticket_id / "source"
    analysis_root = REQUIREMENTS_ROOT / ticket_id / "analysis"
    warnings: list[str] = []

    if not source_root.exists():
        warnings.append(f"Missing source folder: {source_root}")

    source_files = _collect_source_text_files(source_root) if source_root.exists() else []
    source_texts = [
        (path, _safe_read_text(path, warnings))
        for path in source_files
    ]

    layers, layer_figma_files = (
        _load_figma_layers(source_root, warnings)
        if source_root.exists()
        else ([], [])
    )
    screens, screen_figma_files = (
        _load_figma_screens(source_root, warnings)
        if source_root.exists()
        else ([], [])
    )
    source_files_count = len(source_files)
    screen_count = len(screens)
    detected_mode = _detect_compact_context_mode(
        source_files_count=source_files_count,
        screen_count=screen_count,
    )

    if detected_mode == "FIGMA_ONLY" and FIGMA_ONLY_WARNING not in warnings:
        warnings.append(FIGMA_ONLY_WARNING)

    screen_inventory = {
        "ticket_id": ticket_id,
        "screens": screens,
    }
    evidence_index = {
        "ticket_id": ticket_id,
        "source_files": [_relative(path) for path in source_files],
        "source_files_count": source_files_count,
        "figma_files": sorted(set(layer_figma_files + screen_figma_files)),
        "screen_count": screen_count,
        "section_count": len({layer.get("node_id") for layer in layers if layer.get("node_id")}),
        "detected_mode": detected_mode,
        "warnings": warnings,
    }
    chunks = build_requirement_chunks(ticket_id)
    partial_summary_count = len(
        [
            chunk
            for chunk in chunks
            if chunk.get("partial_summary_path")
            and Path(chunk.get("partial_summary_path", "")).exists()
        ]
    )
    evidence_index["chunk_count"] = len(chunks)
    evidence_index["partial_summary_count"] = partial_summary_count

    compact_context = _build_merged_compact_markdown(
        ticket_id=ticket_id,
        source_texts=source_texts,
        layers=layers,
        screens=screens,
        evidence_index=evidence_index,
        chunks=chunks,
        warnings=warnings,
    )
    max_chars = _env_int(
        "REQUIREMENT_COMPACT_CONTEXT_MAX_CHARS",
        DEFAULT_MAX_CONTEXT_CHARS,
    )
    compact_context, truncated = _truncate_context_if_needed(
        context=compact_context,
        max_chars=max_chars,
    )

    if truncated:
        evidence_index["warnings"].append(
            f"Compact context truncated at {max_chars} chars."
        )

    _write_json_pretty(
        analysis_root / "requirement_evidence_index.json",
        evidence_index,
    )
    _write_json_pretty(
        analysis_root / "screen_inventory.json",
        screen_inventory,
    )
    _write_text(
        analysis_root / "requirement_context_compact.md",
        compact_context,
    )

    return {
        "ticket_id": ticket_id,
        "analysis_root": _relative(analysis_root),
        "requirement_evidence_index_path": _relative(
            analysis_root / "requirement_evidence_index.json"
        ),
        "screen_inventory_path": _relative(analysis_root / "screen_inventory.json"),
        "compact_context_path": _relative(
            analysis_root / "requirement_context_compact.md"
        ),
        "screen_count": evidence_index["screen_count"],
        "section_count": evidence_index["section_count"],
        "source_files_count": evidence_index["source_files_count"],
        "detected_mode": evidence_index["detected_mode"],
        "chunk_count": evidence_index["chunk_count"],
        "partial_summary_count": evidence_index["partial_summary_count"],
        "compact_context_length": len(compact_context),
        "truncated": truncated,
        "warnings": evidence_index["warnings"],
    }
