import json
import os
import re
from pathlib import Path
from typing import Any


REQUIREMENTS_ROOT = Path("requirements")
DEFAULT_MAX_CONTEXT_CHARS = 60_000
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

    compact_context = _build_compact_markdown(
        ticket_id=ticket_id,
        source_texts=source_texts,
        layers=layers,
        screens=screens,
        evidence_index=evidence_index,
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
        "compact_context_length": len(compact_context),
        "warnings": evidence_index["warnings"],
    }
