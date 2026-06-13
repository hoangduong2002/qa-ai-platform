import os
import sys

from app.config.env_loader import load_project_env

from app.services.llm_router_service import (
    PROVIDER_DEEPSEEK,
    PROVIDER_LOCAL_COMPACT,
    PROVIDER_LOCAL_TEXT,
    PROVIDER_SKIP,
    TASK_COMPACT_CONTEXT,
    TASK_REQUIREMENT_ANALYSIS,
    call_llm_with_fallback,
    resolve_provider_for_task,
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
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")

    expected = {
        "NO_LLM": PROVIDER_SKIP,
        "TEST_LOCAL_ONLY": PROVIDER_LOCAL_TEXT,
        "PRODUCTION_HYBRID": PROVIDER_DEEPSEEK,
        "DEEPSEEK_ONLY": PROVIDER_DEEPSEEK,
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
    assert "This action requires LLM" in result["reason"]


def test_production_hybrid_requirement_analysis_resolves_to_deepseek(monkeypatch):
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "PRODUCTION_HYBRID",
    )

    assert result["provider"] == PROVIDER_DEEPSEEK


def test_production_hybrid_compact_uses_local_when_configured(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("FORCE_DISABLE_LOCAL_AI", "false")

    result = resolve_provider_for_task(
        TASK_COMPACT_CONTEXT,
        "PRODUCTION_HYBRID",
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
        print("- Or set NON_PORTAL_AI_MODE=PRODUCTION_HYBRID and DEEPSEEK_API_KEY.")
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
