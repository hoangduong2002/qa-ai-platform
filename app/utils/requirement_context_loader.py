import os
from pathlib import Path


DEFAULT_LLM_CONTEXT_MAX_CHARS = 60_000
TRUNCATION_NOTE = "[TRUNCATED BY REQUIREMENT_LLM_CONTEXT_MAX_CHARS]"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""

    return path.read_text(
        encoding="utf-8",
        errors="ignore",
    ).strip()


def _trim_context(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False

    note = f"\n\n{TRUNCATION_NOTE}\n"
    keep_chars = max(max_chars - len(note), 0)
    return text[:keep_chars].rstrip() + note, True


def _log_context_choice(metadata: dict) -> None:
    print(
        "Using requirement context source: "
        f"{metadata.get('context_source', '')}, "
        f"length={metadata.get('context_length', 0)}, "
        f"path={metadata.get('context_path', '')}"
    )


def load_requirement_context_for_llm(ticket_id: str) -> tuple[str, dict]:
    base_dir = Path("requirements") / ticket_id
    analysis_dir = base_dir / "analysis"
    source_dir = base_dir / "source"
    compact_file = analysis_dir / "requirement_context_compact.md"

    max_chars = _env_int(
        "REQUIREMENT_LLM_CONTEXT_MAX_CHARS",
        DEFAULT_LLM_CONTEXT_MAX_CHARS,
    )

    context = _read_text(compact_file)
    context_source = "compact"
    context_path = compact_file

    if not context:
        fallback_candidates = [
            analysis_dir / "sanitized_requirement.md",
            source_dir / "sanitized_requirement.md",
            source_dir / "jira_requirement.md",
            source_dir / "description.md",
        ]

        context_source = "sanitized"
        context_path = fallback_candidates[0]

        for candidate in fallback_candidates:
            context = _read_text(candidate)

            if context:
                context_path = candidate
                break

    context, truncated = _trim_context(
        text=context,
        max_chars=max_chars,
    )

    metadata = {
        "context_source": context_source,
        "context_path": str(context_path),
        "compact_context_path": str(compact_file) if context_source == "compact" else "",
        "context_length": len(context),
        "truncated": truncated,
        "max_chars": max_chars,
    }

    _log_context_choice(metadata)

    return context, metadata
