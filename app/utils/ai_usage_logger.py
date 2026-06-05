import json
from pathlib import Path
from datetime import datetime


def get_usage_log_file() -> Path:
    path = Path("reports")
    path.mkdir(parents=True, exist_ok=True)
    return path / "ai_usage_logs.jsonl"


def log_ai_usage(
    ticket_id: str,
    node_name: str,
    model: str,
    provider: str,
    prompt: str,
    response: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    duration_seconds: float | None = None
):
    record = {
        "timestamp": datetime.now().isoformat(),
        "ticket_id": ticket_id,
        "node_name": node_name,
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        "duration_seconds": duration_seconds,
        "prompt_chars": len(prompt or ""),
        "response_chars": len(response or "")
    }

    with get_usage_log_file().open("a", encoding="utf-8") as file:
        file.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )