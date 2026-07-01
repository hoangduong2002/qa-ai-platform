import os
import sys

from app.config.env_loader import load_project_env

from app.services.llm_router_service import (
    PROVIDER_COPILOT,
    PROVIDER_DEEPSEEK,
    PROVIDER_LOCAL_COMPACT,
    PROVIDER_LOCAL_TEXT,
    PROVIDER_SKIP,
    TASK_COMPACT_CONTEXT,
    TASK_REQUIREMENT_ANALYSIS,
    TASK_REQUIREMENT_SUMMARY,
    _call_copilot,
    call_llm_with_fallback,
    call_text_llm,
    resolve_provider_for_task,
    test_all_llm_providers as run_test_all_llm_providers,
)


load_project_env()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _provider_notes() -> list[str]:
    notes: list[str] = []
    ai_mode = os.getenv("NON_PORTAL_AI_MODE") or os.getenv("PORTAL_DEFAULT_AI_MODE", "NO_LLM")
    notes.append(f"AI_MODE={ai_mode}")
    notes.append(f"LOCAL_BASE_URL={'set' if os.getenv('LOCAL_BASE_URL') else 'missing'}")
    notes.append(f"DEEPSEEK_API_KEY={'set' if os.getenv('DEEPSEEK_API_KEY') else 'missing'}")
    return notes


def test_resolve_provider_for_requirement_analysis_all_primary_modes(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")

    expected = {
        "NO_LLM": PROVIDER_SKIP,
        "TEST_LOCAL_ONLY": PROVIDER_LOCAL_TEXT,
        "PRODUCTION_HYBRID": PROVIDER_DEEPSEEK,
        "PRODUCTION_HYBRID_DEEPSEEK": PROVIDER_DEEPSEEK,
        "PRODUCTION_HYBRID_COPILOT": PROVIDER_COPILOT,
        "DEEPSEEK_ONLY": PROVIDER_DEEPSEEK,
        "COPILOT_ONLY": PROVIDER_COPILOT,
    }

    for ai_mode, provider in expected.items():
        result = resolve_provider_for_task(TASK_REQUIREMENT_ANALYSIS, ai_mode)
        assert result["provider"] == provider


def test_test_local_only_requirement_analysis_resolves_to_local_text(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "TEST_LOCAL_ONLY",
    )

    assert result["provider"] == PROVIDER_LOCAL_TEXT


def test_no_llm_requirement_analysis_resolves_to_skip(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = resolve_provider_for_task(TASK_REQUIREMENT_ANALYSIS, "NO_LLM")

    assert result["provider"] == PROVIDER_SKIP
    assert "This action requires an LLM" in result["reason"]


def test_legacy_production_hybrid_requirement_analysis_resolves_to_deepseek(monkeypatch):
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "PRODUCTION_HYBRID",
    )

    assert result["provider"] == PROVIDER_DEEPSEEK
    assert result["ai_mode"] == "PRODUCTION_HYBRID_DEEPSEEK"


def test_production_hybrid_deepseek_routes_text_to_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_SUMMARY,
        "PRODUCTION_HYBRID_DEEPSEEK",
    )

    assert result["provider"] == PROVIDER_DEEPSEEK


def test_production_hybrid_copilot_routes_text_to_copilot(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_SUMMARY,
        "PRODUCTION_HYBRID_COPILOT",
    )

    assert result["provider"] == PROVIDER_COPILOT


def test_deepseek_only_routes_to_deepseek_and_not_copilot(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(TASK_REQUIREMENT_SUMMARY, "DEEPSEEK_ONLY")

    assert result["provider"] == PROVIDER_DEEPSEEK
    assert result["provider"] != PROVIDER_COPILOT


def test_copilot_only_routes_to_copilot_and_not_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(TASK_REQUIREMENT_SUMMARY, "COPILOT_ONLY")

    assert result["provider"] == PROVIDER_COPILOT
    assert result["provider"] != PROVIDER_DEEPSEEK


def test_production_hybrid_compact_uses_local_when_configured(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")

    result = resolve_provider_for_task(
        TASK_COMPACT_CONTEXT,
        "PRODUCTION_HYBRID_COPILOT",
    )

    assert result["provider"] == PROVIDER_LOCAL_COMPACT


def test_test_local_only_never_falls_back_to_deepseek(monkeypatch):
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "TEST_LOCAL_ONLY",
    )

    assert result["provider"] == PROVIDER_SKIP
    assert "LOCAL_BASE_URL is missing" in result["reason"]


def test_test_local_only_never_routes_to_remote_providers(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "TEST_LOCAL_ONLY",
    )

    assert result["provider"] == PROVIDER_LOCAL_TEXT
    assert result["provider"] not in {PROVIDER_DEEPSEEK, PROVIDER_COPILOT}


def test_no_llm_never_routes_to_any_provider(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")

    result = resolve_provider_for_task(TASK_REQUIREMENT_ANALYSIS, "NO_LLM")

    assert result["provider"] == PROVIDER_SKIP


def test_force_disable_copilot_blocks_with_friendly_error(monkeypatch):
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")

    try:
        call_text_llm(
            task_type=TASK_REQUIREMENT_ANALYSIS,
            prompt="hello",
            ai_mode="COPILOT_ONLY",
        )
    except RuntimeError as error:
        assert str(error) == "Copilot provider is disabled by FORCE_DISABLE_COPILOT=true."
    else:
        raise AssertionError("Expected Copilot force-disable RuntimeError.")


def test_call_copilot_parses_choices_message_content(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "copilot response",
                        },
                    },
                ],
            }

    calls = {}

    def fake_post(url, headers, json, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("COPILOT_BASE_URL", "http://localhost:3100/v1/chat/completions")
    monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4.6")
    monkeypatch.setenv("COPILOT_TIMEOUT", "120")
    monkeypatch.delenv("COPILOT_API_KEY", raising=False)
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")
    monkeypatch.setattr("app.services.llm_router_service.requests.post", fake_post)

    content, raw = _call_copilot("hello", system_prompt="be brief")

    assert content == "copilot response"
    assert raw["choices"][0]["message"]["content"] == "copilot response"
    assert calls["url"] == "http://localhost:3100/v1/chat/completions"
    assert calls["headers"] == {"Content-Type": "application/json"}
    assert calls["json"]["model"] == "claude-sonnet-4.6"
    assert calls["json"]["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]


def _health_result_for(result: dict, provider: str) -> dict:
    for item in result["results"]:
        if item["provider"] == provider:
            return item
    raise AssertionError(f"Provider result not found: {provider}")


def test_health_deepseek_disabled_returns_disabled(monkeypatch):
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")

    result = run_test_all_llm_providers()

    assert _health_result_for(result, PROVIDER_DEEPSEEK)["status"] == "DISABLED"


def test_health_deepseek_missing_key_returns_skipped(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")

    result = run_test_all_llm_providers()

    assert _health_result_for(result, PROVIDER_DEEPSEEK)["status"] == "SKIPPED"


def test_health_copilot_enabled_without_api_key_attempts_call(monkeypatch):
    calls = []

    def fake_call(provider, prompt, system_prompt, response_format, **kwargs):
        calls.append(provider)
        return "OK", {}

    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")
    monkeypatch.setenv("COPILOT_BASE_URL", "http://localhost:3100/v1/chat/completions")
    monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4.6")
    monkeypatch.delenv("COPILOT_API_KEY", raising=False)
    monkeypatch.setattr("app.services.llm_router_service._call_provider", fake_call)

    result = run_test_all_llm_providers()

    assert PROVIDER_COPILOT in calls
    assert _health_result_for(result, PROVIDER_COPILOT)["status"] == "OK"


def test_health_copilot_disabled_returns_disabled(monkeypatch):
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")

    result = run_test_all_llm_providers()

    assert _health_result_for(result, PROVIDER_COPILOT)["status"] == "DISABLED"


def test_health_local_disabled_returns_disabled(monkeypatch):
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")

    result = run_test_all_llm_providers()

    assert _health_result_for(result, PROVIDER_LOCAL_TEXT)["status"] == "DISABLED"


def test_health_local_missing_base_url_or_model_returns_skipped(monkeypatch):
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_TEXT_MODEL", raising=False)

    result = run_test_all_llm_providers()

    assert _health_result_for(result, PROVIDER_LOCAL_TEXT)["status"] == "SKIPPED"


def test_health_local_text_uses_ollama_api_chat_payload(monkeypatch):
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "role": "assistant",
                    "content": "OK",
                },
                "done": True,
            }

    def fake_post(url, headers, json, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")
    monkeypatch.setenv("LOCAL_BASE_URL", "http://172.76.10.44:11434")
    monkeypatch.setenv("LOCAL_TEXT_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("LLM_HEALTH_CHECK_TIMEOUT", "30")
    monkeypatch.setattr("app.services.llm_router_service.requests.post", fake_post)

    result = run_test_all_llm_providers()
    local = _health_result_for(result, PROVIDER_LOCAL_TEXT)

    assert local["status"] == "OK"
    assert local["message"] == "Provider is working."
    assert calls["url"] == "http://172.76.10.44:11434/api/chat"
    assert "/v1/chat/completions" not in calls["url"]
    assert calls["headers"] == {"Content-Type": "application/json"}
    assert calls["json"] == {
        "model": "qwen2.5:14b",
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: OK",
            },
        ],
        "stream": False,
    }
    assert calls["timeout"] == 30.0


def test_health_local_text_invalid_response_is_failed_with_diagnostics(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "done": True,
            }

    def fake_post(url, headers, json, timeout):
        return FakeResponse()

    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")
    monkeypatch.setenv("LOCAL_BASE_URL", "http://172.76.10.44:11434")
    monkeypatch.setenv("LOCAL_TEXT_MODEL", "qwen2.5:14b")
    monkeypatch.setattr("app.services.llm_router_service.requests.post", fake_post)

    result = run_test_all_llm_providers()
    local = _health_result_for(result, PROVIDER_LOCAL_TEXT)

    assert local["status"] == "FAILED"
    assert local["provider"] == PROVIDER_LOCAL_TEXT
    assert local["model"] == "qwen2.5:14b"
    assert local["base_url"] == "http://172.76.10.44:11434"
    assert local["resolved_url"] == "http://172.76.10.44:11434/api/chat"
    assert local["exception_type"] == "RuntimeError"
    assert "message.content" in local["error"]
    assert isinstance(local["duration_ms"], int)


def test_health_provider_exception_returns_failed(monkeypatch):
    def fake_call(provider, prompt, system_prompt, response_format, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "true")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")
    monkeypatch.setenv("COPILOT_BASE_URL", "http://localhost:3100/v1/chat/completions")
    monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4.6")
    monkeypatch.setattr("app.services.llm_router_service._call_provider", fake_call)

    result = run_test_all_llm_providers()
    copilot = _health_result_for(result, PROVIDER_COPILOT)

    assert copilot["status"] == "FAILED"
    assert copilot["error"] == "provider unavailable"


def test_health_overall_false_when_enabled_provider_fails(monkeypatch):
    def fake_call(provider, prompt, system_prompt, response_format, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "true")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")
    monkeypatch.setattr("app.services.llm_router_service._call_provider", fake_call)

    result = run_test_all_llm_providers()

    assert result["ok"] is False
    assert _health_result_for(result, PROVIDER_DEEPSEEK)["status"] == "FAILED"


def test_health_overall_true_when_enabled_pass_and_others_skipped_or_disabled(monkeypatch):
    def fake_call(provider, prompt, system_prompt, response_format, **kwargs):
        return "OK", {}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FORCE_DISABLE_DEEPSEEK", "false")
    monkeypatch.delenv("COPILOT_BASE_URL", raising=False)
    monkeypatch.setenv("FORCE_DISABLE_COPILOT", "false")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "true")
    monkeypatch.setattr("app.services.llm_router_service._call_provider", fake_call)

    result = run_test_all_llm_providers()

    assert result["ok"] is True
    assert _health_result_for(result, PROVIDER_DEEPSEEK)["status"] == "OK"
    assert _health_result_for(result, PROVIDER_COPILOT)["status"] == "SKIPPED"
    assert _health_result_for(result, PROVIDER_LOCAL_TEXT)["status"] == "DISABLED"


def main() -> int:
    print("LLM router compact_context smoke test")

    for note in _provider_notes():
        print(f"- {note}")

    prompt = """
Ticket: QA-ROUTER-SMOKE
Requirement:
- User can submit a login form with email and password.
- Email is required and must be valid.
- Password is required.
- Show an error message when validation fails.

Return a compact QA context in Markdown.
""".strip()

    try:
        result = call_llm_with_fallback(
            task_type="compact_context",
            prompt=prompt,
            system_prompt="You compact QA requirements. Return concise Markdown only.",
        )
    except Exception as error:
        print()
        print("LLM router test failed with a clear configuration/runtime error:")
        print(error)
        print()
        print("Expected local-free test setup options:")
        print("- Set NON_PORTAL_AI_MODE=TEST_LOCAL_ONLY and LOCAL_BASE_URL.")
        print("- Or set NON_PORTAL_AI_MODE=PRODUCTION_HYBRID_DEEPSEEK and DEEPSEEK_API_KEY.")
        return 1

    print()
    print("Provider used:", result.provider)
    print("Model used:", result.model)
    print("Fallback used:", result.fallback_used)
    print("Duration seconds:", round(result.duration_seconds, 2))
    print("Input chars:", result.input_chars)
    print("Output chars:", result.output_chars)
    print()
    print("Response preview:")
    print(result.content[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
