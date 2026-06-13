import os
import sys

from dotenv import load_dotenv

from app.services.llm_router_service import (
    PROVIDER_DEEPSEEK,
    PROVIDER_OLLAMA_TEXT,
    PROVIDER_SKIP,
    TASK_REQUIREMENT_ANALYSIS,
    call_llm_with_fallback,
    resolve_provider_for_task,
)


load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _provider_notes() -> list[str]:
    notes: list[str] = []
    primary = os.getenv("COMPACT_LLM_PRIMARY", "LOCAL_COMPACT").strip().upper()
    fallback = os.getenv("COMPACT_LLM_FALLBACK", "DEEPSEEK").strip().upper()

    if primary.startswith("LOCAL") and not (
        os.getenv("LOCAL_TEXT_BASE_URL") or os.getenv("LOCAL_BASE_URL")
    ):
        notes.append(
            "LOCAL_TEXT_BASE_URL/LOCAL_BASE_URL is not set; using http://localhost:11434."
        )

    if primary == "DEEPSEEK" or fallback == "DEEPSEEK":
        if not os.getenv("DEEPSEEK_API_KEY"):
            notes.append(
                "DEEPSEEK_API_KEY is missing; DeepSeek fallback cannot be used."
            )

    notes.append(f"COMPACT_LLM_PRIMARY={primary or '[empty]'}")
    notes.append(f"COMPACT_LLM_FALLBACK={fallback or '[empty]'}")
    return notes


def test_resolve_provider_for_requirement_analysis_all_primary_modes(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_ENABLED", "true")

    expected = {
        "NO_LLM": PROVIDER_SKIP,
        "TEST_LOCAL_ONLY": PROVIDER_OLLAMA_TEXT,
        "PRODUCTION_HYBRID": PROVIDER_DEEPSEEK,
        "DEEPSEEK_ONLY": PROVIDER_DEEPSEEK,
    }

    for ai_mode, provider in expected.items():
        result = resolve_provider_for_task(TASK_REQUIREMENT_ANALYSIS, ai_mode)
        assert result["provider"] == provider


def test_test_local_only_requirement_analysis_resolves_to_ollama_text(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_ENABLED", "true")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "TEST_LOCAL_ONLY",
    )

    assert result["provider"] == PROVIDER_OLLAMA_TEXT


def test_no_llm_requirement_analysis_resolves_to_skip(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_ENABLED", "true")

    result = resolve_provider_for_task(TASK_REQUIREMENT_ANALYSIS, "NO_LLM")

    assert result["provider"] == PROVIDER_SKIP
    assert "This action requires LLM" in result["reason"]


def test_production_hybrid_requirement_analysis_resolves_to_deepseek(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_ENABLED", "false")
    monkeypatch.setenv("DEEPSEEK_ENABLED", "true")

    result = resolve_provider_for_task(
        TASK_REQUIREMENT_ANALYSIS,
        "PRODUCTION_HYBRID",
    )

    assert result["provider"] == PROVIDER_DEEPSEEK


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
        print("- Run LOCAL and set COMPACT_LLM_PRIMARY=LOCAL_COMPACT.")
        print("- Or set COMPACT_LLM_PRIMARY=DEEPSEEK and DEEPSEEK_API_KEY.")
        print("- Or keep Qwen primary and set DEEPSEEK_API_KEY for fallback.")
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
