import json
from typing import Any


PROVIDER_ERROR_MARKERS = (
    "provider",
    "deepseek",
    "local ai",
    "local_",
    "ollama",
    "no_llm",
    "requires an llm",
    "requires llm",
    "blocked",
    "unavailable",
    "not available",
    "api_key",
    "payment required",
    "402",
    "json",
)


def _message(error: Exception | str) -> str:
    return str(error).strip() or "Unknown provider error."


def classify_provider_error(error: Exception | str) -> str:
    message = _message(error)
    lowered = message.lower()

    if "402" in lowered or "payment required" in lowered:
        return "deepseek_payment_required"

    if "force_disable_deepseek" in lowered or "deepseek is disabled" in lowered:
        return "deepseek_force_disabled"

    if "deepseek_api_key" in lowered and "missing" in lowered:
        return "deepseek_missing_api_key"

    if "no_llm" in lowered or "requires an llm" in lowered or "requires llm" in lowered:
        return "no_llm_blocked"

    if (
        "local ai" in lowered
        or "local_base_url" in lowered
        or "ollama" in lowered
        or "local vision" in lowered
        or "cannot connect to local" in lowered
    ):
        return "local_unavailable"

    if (
        isinstance(error, json.JSONDecodeError)
        or "non-json" in lowered
        or "non json" in lowered
        or "invalid json" in lowered
        or "must be valid json" in lowered
        or "expecting value" in lowered
        or "failed to parse" in lowered
        or "parse_json" in lowered
    ):
        return "provider_non_json"

    if any(marker in lowered for marker in PROVIDER_ERROR_MARKERS):
        return "provider_error"

    return "unknown"


def _friendly_detail(error: Exception | str, classification: str) -> str:
    original = _message(error)

    if classification == "deepseek_missing_api_key":
        return "DeepSeek is unavailable because DEEPSEEK_API_KEY is missing."

    if classification == "deepseek_payment_required":
        return (
            "DeepSeek returned 402 Payment Required. Check account balance, "
            "billing, or model access."
        )

    if classification == "deepseek_force_disabled":
        return "DeepSeek is disabled by FORCE_DISABLE_DEEPSEEK=true."

    if classification == "local_unavailable":
        return (
            "Local/Ollama provider is unavailable. Check LOCAL_BASE_URL, "
            "LOCAL model settings, and that Ollama is running."
        )

    if classification == "no_llm_blocked":
        return (
            "AI mode is NO_LLM. This action requires an LLM. "
            "Select TEST_LOCAL_ONLY, DEEPSEEK_ONLY, or PRODUCTION_HYBRID."
        )

    if classification == "provider_non_json":
        return (
            "The AI provider returned a response that could not be parsed as "
            f"the required JSON. Original error: {original}"
        )

    return original


def format_provider_error(
    error: Exception | str,
    ai_mode: str | None,
    source_channel: str | None,
) -> str:
    classification = classify_provider_error(error)

    if classification == "unknown":
        return _message(error)

    channel = (source_channel or "unknown").strip().lower()
    mode = (ai_mode or "UNKNOWN").strip().upper()
    detail = _friendly_detail(error, classification)

    return (
        f"AI provider error for {channel} AI_MODE={mode}.\n"
        f"{detail}"
    )
