import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = {
    "DEEPSEEK",
    "LOCAL_TEXT",
    "LOCAL_VISION",
    "LOCAL_COMPACT",
}

TASK_DEFAULTS = {
    "compact_context": ("LOCAL_COMPACT", "DEEPSEEK"),
    "compact": ("LOCAL_COMPACT", "DEEPSEEK"),
    "text_generation": ("DEEPSEEK", "LOCAL_TEXT"),
    "text_analyze": ("DEEPSEEK", "LOCAL_TEXT"),
    "analyze": ("DEEPSEEK", "LOCAL_TEXT"),
    "vision": ("LOCAL_VISION", ""),
}


@dataclass
class LLMRouterResponse:
    content: str
    provider: str
    model: str
    fallback_used: bool
    duration_seconds: float
    input_chars: int
    output_chars: int
    raw: dict[str, Any] | None = None


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except Exception:
        return default


def _normalize_provider(provider: str) -> str:
    normalized = (provider or "").strip().upper()

    if normalized == "LOCAL":
        return "LOCAL_TEXT"

    if normalized == "QWEN":
        return "LOCAL_TEXT"

    return normalized


def _task_env_prefix(task_type: str) -> str:
    normalized = (task_type or "").strip().lower()

    if normalized in {"compact", "compact_context"}:
        return "COMPACT_LLM"

    if normalized == "vision":
        return "VISION_LLM"

    return "TEXT_LLM"


def _resolve_providers(task_type: str) -> list[str]:
    normalized_task = (task_type or "").strip().lower()
    prefix = _task_env_prefix(normalized_task)
    default_primary, default_fallback = TASK_DEFAULTS.get(
        normalized_task,
        TASK_DEFAULTS["text_generation"],
    )

    primary = _normalize_provider(
        _env_str(f"{prefix}_PRIMARY", default_primary)
    )
    fallback = _normalize_provider(
        _env_str(f"{prefix}_FALLBACK", default_fallback)
    )
    providers = [provider for provider in [primary, fallback] if provider]

    return list(dict.fromkeys(providers))


def _provider_model(provider: str) -> str:
    if provider == "DEEPSEEK":
        return _env_str("DEEPSEEK_MODEL", "deepseek-chat")

    if provider == "LOCAL_COMPACT":
        return (
            _env_str("COMPACT_LLM_MODEL")
            or _env_str("LOCAL_COMPACT_MODEL")
            or _env_str("LOCAL_TEXT_MODEL", "qwen2.5:14b")
        )

    if provider == "LOCAL_VISION":
        return _env_str("LOCAL_VISION_MODEL", "qwen2.5vl:7b")

    if provider == "LOCAL_TEXT":
        return _env_str("LOCAL_TEXT_MODEL", "qwen2.5:14b")

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _provider_timeout(provider: str) -> float:
    if provider == "DEEPSEEK":
        return _env_float("DEEPSEEK_TIMEOUT", 120)

    if provider == "LOCAL_COMPACT":
        return _env_float(
            "COMPACT_LLM_TIMEOUT",
            _env_float("LOCAL_TEXT_TIMEOUT", 180),
        )

    if provider == "LOCAL_VISION":
        return _env_float("LOCAL_VISION_TIMEOUT", 180)

    if provider == "LOCAL_TEXT":
        return _env_float("LOCAL_TEXT_TIMEOUT", 180)

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _LOCAL_base_url(provider: str) -> str:
    if provider == "LOCAL_VISION":
        return (
            _env_str("LOCAL_VISION_BASE_URL")
            or _env_str("LOCAL_TEXT_BASE_URL")
            or _env_str("LOCAL_BASE_URL")
            or "http://localhost:11434"
        ).rstrip("/")

    return (
        _env_str("LOCAL_TEXT_BASE_URL")
        or _env_str("LOCAL_BASE_URL")
        or "http://localhost:11434"
    ).rstrip("/")


def _deepseek_chat_completions_url() -> str:
    configured = _env_str(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/chat/completions",
    ).rstrip("/")

    if configured.endswith("/chat/completions"):
        return configured

    return f"{configured}/chat/completions"


def _messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": prompt})
    return messages


def _call_deepseek(
    prompt: str,
    system_prompt: str | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    api_key = _env_str("DEEPSEEK_API_KEY")

    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY for DEEPSEEK provider.")

    model = _provider_model("DEEPSEEK")
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages(prompt, system_prompt),
        "temperature": 0,
    }

    if response_format:
        payload["response_format"] = response_format

    response = requests.post(
        _deepseek_chat_completions_url(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_provider_timeout("DEEPSEEK"),
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]

    return content, data


def _call_LOCAL(
    provider: str,
    prompt: str,
    system_prompt: str | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": _provider_model(provider),
        "messages": _messages(prompt, system_prompt),
        "stream": False,
    }

    if response_format:
        payload["format"] = response_format

    response = requests.post(
        f"{_LOCAL_base_url(provider)}/api/chat",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=_provider_timeout(provider),
    )
    response.raise_for_status()
    data = response.json()
    content = (
        data.get("message", {}).get("content")
        or data.get("response")
        or ""
    )

    if not content.strip():
        raise RuntimeError(f"{provider} returned an empty response.")

    return content, data


def _call_provider(
    provider: str,
    prompt: str,
    system_prompt: str | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    if provider == "DEEPSEEK":
        return _call_deepseek(prompt, system_prompt, response_format)

    return _call_LOCAL(provider, prompt, system_prompt, response_format)


def call_llm_with_fallback(
    task_type: str,
    prompt: str,
    system_prompt: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> LLMRouterResponse:
    providers = _resolve_providers(task_type)

    if not providers:
        raise RuntimeError(f"No LLM providers configured for task_type={task_type!r}.")

    errors: list[str] = []
    input_chars = len(prompt or "") + len(system_prompt or "")

    for index, provider in enumerate(providers):
        model = _provider_model(provider)
        started = time.time()

        try:
            content, raw = _call_provider(
                provider=provider,
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format,
            )
            duration = time.time() - started
            fallback_used = index > 0
            output_chars = len(content or "")

            logger.info(
                "LLM router success task_type=%s provider=%s model=%s "
                "fallback_used=%s duration_seconds=%.2f input_chars=%s output_chars=%s",
                task_type,
                provider,
                model,
                fallback_used,
                duration,
                input_chars,
                output_chars,
            )

            return LLMRouterResponse(
                content=content,
                provider=provider,
                model=model,
                fallback_used=fallback_used,
                duration_seconds=duration,
                input_chars=input_chars,
                output_chars=output_chars,
                raw=raw,
            )
        except Exception as error:
            duration = time.time() - started
            message = f"{provider}/{model}: {type(error).__name__}: {error}"
            errors.append(message)
            logger.warning(
                "LLM router provider failed task_type=%s provider=%s model=%s "
                "duration_seconds=%.2f input_chars=%s error=%s",
                task_type,
                provider,
                model,
                duration,
                input_chars,
                error,
            )

    raise RuntimeError(
        "All LLM providers failed for "
        f"task_type={task_type!r}. Tried: {'; '.join(errors)}"
    )
