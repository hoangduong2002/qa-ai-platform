import json
import os
from pathlib import Path
from datetime import datetime


DEFAULT_AI_USAGE_LOG_PATH = "runtime/ai_usage_logs.jsonl"


def get_usage_log_file() -> Path:
    log_file = Path(os.getenv("AI_USAGE_LOG_PATH", DEFAULT_AI_USAGE_LOG_PATH))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return log_file


def _estimate_tokens(chars: int | None) -> int | None:
    if chars is None:
        return None

    return max(round(chars / 4), 1) if chars > 0 else 0


def _extract_input_tokens(raw_usage: dict | None) -> int | None:
    if not isinstance(raw_usage, dict):
        return None

    usage = raw_usage.get("usage") if isinstance(raw_usage.get("usage"), dict) else {}
    return (
        raw_usage.get("prompt_eval_count")
        or raw_usage.get("prompt_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input_tokens")
    )


def _extract_output_tokens(raw_usage: dict | None) -> int | None:
    if not isinstance(raw_usage, dict):
        return None

    usage = raw_usage.get("usage") if isinstance(raw_usage.get("usage"), dict) else {}
    return (
        raw_usage.get("eval_count")
        or raw_usage.get("completion_tokens")
        or usage.get("completion_tokens")
        or usage.get("output_tokens")
    )


def log_ai_usage(
    ticket_id: str,
    node_name: str,
    model: str,
    provider: str,
    prompt: str,
    response: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    duration_seconds: float | None = None,
    ai_mode: str = "",
    task_type: str = "",
    source_channel: str = "",
    job_id: str = "",
    duration_ms: int | None = None,
    status: str = "success",
    error_type: str = "",
    raw_usage: dict | None = None,
):
    input_chars = len(prompt or "")
    output_chars = len(response or "")
    input_tokens = input_tokens if input_tokens is not None else _extract_input_tokens(raw_usage)
    output_tokens = output_tokens if output_tokens is not None else _extract_output_tokens(raw_usage)

    if duration_ms is None and duration_seconds is not None:
        duration_ms = int(duration_seconds * 1000)

    if duration_seconds is None and duration_ms is not None:
        duration_seconds = duration_ms / 1000

    record = {
        "timestamp": datetime.now().isoformat(),
        "ticket_id": ticket_id,
        "job_id": job_id,
        "node_name": node_name,
        "task_type": task_type,
        "source_channel": source_channel,
        "ai_mode": ai_mode,
        "provider": provider,
        "model": model,
        "status": status,
        "error_type": error_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        "estimated_input_tokens": _estimate_tokens(input_chars),
        "estimated_output_tokens": _estimate_tokens(output_chars),
        "duration_ms": duration_ms,
        "duration_seconds": duration_seconds,
        "input_chars": input_chars,
        "output_chars": output_chars,
        "prompt_chars": input_chars,
        "response_chars": output_chars,
    }

    with get_usage_log_file().open("a", encoding="utf-8") as file:
        file.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )
