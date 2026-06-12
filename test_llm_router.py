import os
import sys

from dotenv import load_dotenv

from app.services.llm_router_service import call_llm_with_fallback


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
