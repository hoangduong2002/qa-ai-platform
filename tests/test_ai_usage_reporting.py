import json

from app.services.report_service import load_ai_usage_logs
from app.services.web_report_preview_service import build_report_preview
from app.services.llm_router_service import call_text_llm


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            if isinstance(record, str):
                file.write(record + "\n")
            else:
                file.write(json.dumps(record) + "\n")


def test_report_preview_reads_latest_records_after_december_6(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    monkeypatch.setattr(
        "app.services.web_report_preview_service.list_requirements",
        lambda: [],
    )

    _write_jsonl(
        log_path,
        [
            {
                "timestamp": "2025-12-06T09:00:00",
                "provider": "DEEPSEEK",
                "model": "old-model",
            },
            {
                "timestamp": "2025-12-07T09:00:00",
                "provider": "COPILOT",
                "model": "new-model",
            },
        ],
    )

    preview = build_report_preview()

    assert preview["log_rows"][0]["timestamp"] == "2025-12-07T09:00:00"
    assert preview["log_rows"][0]["provider"] == "COPILOT"


def test_report_loads_usage_logs_sorted_descending(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    _write_jsonl(
        log_path,
        [
            {"timestamp": "2025-12-05T10:00:00", "provider": "DEEPSEEK"},
            {"timestamp": "2025-12-07T10:00:00", "provider": "LOCAL_TEXT"},
            {"timestamp": "2025-12-06T10:00:00", "provider": "COPILOT"},
        ],
    )

    logs = load_ai_usage_logs()

    assert [log["provider"] for log in logs] == [
        "LOCAL_TEXT",
        "COPILOT",
        "DEEPSEEK",
    ]


def test_report_supports_old_and_new_timestamp_field_names(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    _write_jsonl(
        log_path,
        [
            {
                "created_at": "2025-12-07T10:00:00",
                "llm_provider": "COPILOT",
            },
            {
                "time": "2025-12-08T10:00:00",
                "ai_provider": "LOCAL_TEXT",
            },
            {
                "timestamp": "2025-12-06T10:00:00",
                "provider": "DEEPSEEK",
            },
        ],
    )

    logs = load_ai_usage_logs()

    assert [log["timestamp"] for log in logs] == [
        "2025-12-08T10:00:00",
        "2025-12-07T10:00:00",
        "2025-12-06T10:00:00",
    ]
    assert [log["provider"] for log in logs] == [
        "LOCAL_TEXT",
        "COPILOT",
        "DEEPSEEK",
    ]


def test_malformed_jsonl_line_does_not_break_report(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    _write_jsonl(
        log_path,
        [
            {"timestamp": "2025-12-07T10:00:00", "provider": "COPILOT"},
            "{not-json",
            {"timestamp": "2025-12-08T10:00:00", "provider": "LOCAL_TEXT"},
        ],
    )

    logs = load_ai_usage_logs()

    assert len(logs) == 2
    assert [log["provider"] for log in logs] == ["LOCAL_TEXT", "COPILOT"]


def test_call_text_llm_writes_copilot_usage_record(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    monkeypatch.setenv("COPILOT_BASE_URL", "http://localhost:3100/v1/chat/completions")
    monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4.6")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    def fake_call_provider(provider, prompt, system_prompt, response_format, **kwargs):
        return "OK", {"usage": {"prompt_tokens": 4, "completion_tokens": 3}}

    monkeypatch.setattr(
        "app.services.llm_router_service._call_provider",
        fake_call_provider,
    )

    content = call_text_llm(
        task_type="requirement_summary",
        prompt="hello",
        ai_mode="COPILOT_ONLY",
        source_channel="web",
        ticket_id="REQ-1",
        node_name="summary",
    )

    record = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert content == "OK"
    assert record["provider"] == "COPILOT"
    assert record["model"] == "claude-sonnet-4.6"
    assert record["ticket_id"] == "REQ-1"
    assert record["input_tokens"] == 4
    assert record["output_tokens"] == 3
    assert record["status"] == "success"
    assert record["estimated_input_tokens"] is not None
    assert record["estimated_output_tokens"] is not None


def test_call_text_llm_writes_local_text_usage_record(monkeypatch, tmp_path):
    log_path = tmp_path / "ai_usage_logs.jsonl"
    monkeypatch.setenv("AI_USAGE_LOG_PATH", str(log_path))
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LOCAL_TEXT_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")

    def fake_call_provider(provider, prompt, system_prompt, response_format, **kwargs):
        return "OK", {"prompt_eval_count": 3, "eval_count": 2}

    monkeypatch.setattr(
        "app.services.llm_router_service._call_provider",
        fake_call_provider,
    )

    content = call_text_llm(
        task_type="requirement_summary",
        prompt="hello",
        ai_mode="TEST_LOCAL_ONLY",
        source_channel="web",
        ticket_id="REQ-2",
        node_name="summary",
    )

    record = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert content == "OK"
    assert record["provider"] == "LOCAL_TEXT"
    assert record["model"] == "qwen2.5:14b"
    assert record["ticket_id"] == "REQ-2"
    assert record["task_type"] == "requirement_summary"
    assert record["source_channel"] == "web"
    assert record["input_tokens"] == 3
    assert record["output_tokens"] == 2
    assert record["status"] == "success"
