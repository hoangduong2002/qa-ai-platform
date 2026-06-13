import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from app.services.portal_ai_mode_service import (
    assert_deepseek_allowed,
    assert_local_ai_allowed,
    get_current_portal_ai_mode,
)
from app.services.portal_job_service import (
    get_current_job_id,
    limit_llm_call,
    limit_ollama_call,
)


load_dotenv()

logger = logging.getLogger(__name__)


TASK_REQUIREMENT_ANALYSIS = "requirement_analysis"
TASK_REQUIREMENT_SUMMARY = "requirement_summary"
TASK_TEST_STRUCTURE = "test_structure"
TASK_SCENARIO_GENERATION = "scenario_generation"
TASK_TESTCASE_GENERATION = "testcase_generation"
TASK_COVERAGE_REVIEW = "coverage_review"
TASK_FINAL_REVIEW = "final_review"
TASK_CLARIFICATION_GENERATION = "clarification_generation"
TASK_COMPACT_CONTEXT = "compact_context"
TASK_VISION_EXTRACT = "vision_extract"

AI_MODE_TEST_LOCAL_ONLY = "TEST_LOCAL_ONLY"
AI_MODE_PRODUCTION_HYBRID = "PRODUCTION_HYBRID"
AI_MODE_PRODUCTION_REMOTE_ONLY = "PRODUCTION_REMOTE_ONLY"
AI_MODE_DEEPSEEK_ONLY = "DEEPSEEK_ONLY"
AI_MODE_NO_LLM = "NO_LLM"

PROVIDER_DEEPSEEK = "DEEPSEEK"
PROVIDER_OLLAMA_TEXT = "OLLAMA_TEXT"
PROVIDER_OLLAMA_COMPACT = "OLLAMA_COMPACT"
PROVIDER_OLLAMA_VISION = "OLLAMA_VISION"
PROVIDER_RULE_BASED = "RULE_BASED"
PROVIDER_SKIP = "SKIP"

TEXT_REASONING_TASK_TYPES = {
    TASK_REQUIREMENT_ANALYSIS,
    TASK_REQUIREMENT_SUMMARY,
    TASK_TEST_STRUCTURE,
    TASK_SCENARIO_GENERATION,
    TASK_TESTCASE_GENERATION,
    TASK_COVERAGE_REVIEW,
    TASK_FINAL_REVIEW,
    TASK_CLARIFICATION_GENERATION,
}

COMPACT_TASK_TYPES = {TASK_COMPACT_CONTEXT}
VISION_TASK_TYPES = {TASK_VISION_EXTRACT}
VALID_TASK_TYPES = (
    TEXT_REASONING_TASK_TYPES
    | COMPACT_TASK_TYPES
    | VISION_TASK_TYPES
)
VALID_AI_MODES = {
    AI_MODE_TEST_LOCAL_ONLY,
    AI_MODE_PRODUCTION_HYBRID,
    AI_MODE_PRODUCTION_REMOTE_ONLY,
    AI_MODE_DEEPSEEK_ONLY,
    AI_MODE_NO_LLM,
}


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


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = _env_str(name)

    if not value:
        return default

    return value.lower() in {"1", "true", "yes", "y", "on"}


def _deepseek_enabled() -> bool:
    return _env_bool("DEEPSEEK_ENABLED", True)


def _local_ai_enabled() -> bool:
    return _env_bool("LOCAL_AI_ENABLED", False)


def _local_compact_enabled() -> bool:
    if not _local_ai_enabled():
        return False

    return _env_bool("LOCAL_COMPACT_ENABLED", True)


def _local_vision_enabled() -> bool:
    if not _local_ai_enabled():
        return False

    return _env_bool("LOCAL_VISION_ENABLED", True)


def _provider_model_for_resolution(provider: str) -> str:
    if provider == PROVIDER_DEEPSEEK:
        return _env_str("DEEPSEEK_MODEL", "deepseek-chat")

    if provider == PROVIDER_OLLAMA_TEXT:
        return _env_str("OLLAMA_TEXT_MODEL", "qwen2.5:14b")

    if provider == PROVIDER_OLLAMA_COMPACT:
        return _env_str("OLLAMA_COMPACT_MODEL", "qwen2.5:14b")

    if provider == PROVIDER_OLLAMA_VISION:
        return _env_str("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")

    return ""


def _resolve_effective_ai_mode(ai_mode: str | None) -> str:
    if ai_mode:
        return ai_mode.strip().upper()

    portal_mode = get_current_portal_ai_mode()

    if portal_mode and portal_mode.get("ai_mode"):
        return str(portal_mode["ai_mode"]).strip().upper()

    return AI_MODE_NO_LLM


def _ollama_base_url() -> str:
    return _env_str("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _ollama_timeout(provider: str) -> int:
    if provider == PROVIDER_OLLAMA_COMPACT:
        return _env_int("OLLAMA_COMPACT_TIMEOUT", _env_int("LOCAL_TEXT_TIMEOUT", 180))

    return _env_int("OLLAMA_TEXT_TIMEOUT", _env_int("LOCAL_TEXT_TIMEOUT", 180))


def _provider_result(
    task_type: str,
    ai_mode: str,
    provider: str,
    reason: str,
) -> dict[str, str]:
    result = {
        "task_type": task_type,
        "ai_mode": ai_mode,
        "provider": provider,
        "model": _provider_model_for_resolution(provider),
        "reason": reason,
    }
    logger.info(
        "LLM provider resolved task_type=%s ai_mode=%s provider=%s model=%s reason=%s",
        result["task_type"],
        result["ai_mode"],
        result["provider"],
        result["model"],
        result["reason"],
    )
    return result


def resolve_provider_for_task(task_type: str, ai_mode: str) -> dict[str, str]:
    normalized_task_type = (task_type or "").strip().lower()
    normalized_ai_mode = (ai_mode or "").strip().upper()

    if normalized_task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Unsupported task_type: {task_type}")

    if normalized_ai_mode not in VALID_AI_MODES:
        raise ValueError(f"Unsupported ai_mode: {ai_mode}")

    deepseek_enabled = _deepseek_enabled()
    local_ai_enabled = _local_ai_enabled()
    local_compact_enabled = _local_compact_enabled()
    local_vision_enabled = _local_vision_enabled()
    ollama_base_url = _env_str("OLLAMA_BASE_URL", "http://localhost:11434")

    if normalized_task_type in TEXT_REASONING_TASK_TYPES:
        if normalized_ai_mode == AI_MODE_TEST_LOCAL_ONLY:
            if local_ai_enabled:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_OLLAMA_TEXT,
                    (
                        "TEST_LOCAL_ONLY routes text/reasoning tasks to local "
                        f"provider endpoint at {ollama_base_url}."
                    ),
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                "Local AI is required in TEST_LOCAL_ONLY mode but is not available.",
            )

        if normalized_ai_mode in {AI_MODE_DEEPSEEK_ONLY, AI_MODE_PRODUCTION_REMOTE_ONLY}:
            if deepseek_enabled:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_DEEPSEEK,
                    f"{normalized_ai_mode} routes text/reasoning tasks to DeepSeek.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                "DEEPSEEK_ENABLED=false; remote text/reasoning provider is blocked.",
            )

        if normalized_ai_mode == AI_MODE_PRODUCTION_HYBRID:
            if deepseek_enabled:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_DEEPSEEK,
                    f"{normalized_ai_mode} routes text/reasoning tasks to DeepSeek.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                "DEEPSEEK_ENABLED=false; remote text/reasoning provider is blocked.",
            )

        if normalized_ai_mode == AI_MODE_NO_LLM:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                "This action requires LLM. Select TEST_LOCAL_ONLY or PRODUCTION_HYBRID.",
            )

    if normalized_task_type in COMPACT_TASK_TYPES:
        if normalized_ai_mode in {
            AI_MODE_TEST_LOCAL_ONLY,
            AI_MODE_PRODUCTION_HYBRID,
        }:
            if local_compact_enabled:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_OLLAMA_COMPACT,
                    "Local compact is enabled; compact_context uses OLLAMA_COMPACT.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_RULE_BASED,
                "Local compact is disabled; compact_context uses RULE_BASED.",
            )

        if normalized_ai_mode in {AI_MODE_DEEPSEEK_ONLY, AI_MODE_PRODUCTION_REMOTE_ONLY}:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_RULE_BASED,
                "DEEPSEEK_ONLY/PRODUCTION_REMOTE_ONLY uses RULE_BASED compact_context.",
            )

        if normalized_ai_mode == AI_MODE_NO_LLM:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_RULE_BASED,
                "NO_LLM mode uses RULE_BASED compact_context.",
            )

        return _provider_result(
            normalized_task_type,
            normalized_ai_mode,
            PROVIDER_RULE_BASED,
            "DEEPSEEK_ENABLED=false; compact_context uses RULE_BASED.",
        )

    if normalized_task_type in VISION_TASK_TYPES:
        if normalized_ai_mode in {AI_MODE_PRODUCTION_REMOTE_ONLY, AI_MODE_DEEPSEEK_ONLY}:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                f"{normalized_ai_mode} does not use local vision.",
            )

        if normalized_ai_mode == AI_MODE_NO_LLM:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                "NO_LLM mode disables all vision providers.",
            )

        if local_vision_enabled:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_OLLAMA_VISION,
                "Local vision is enabled; vision_extract uses OLLAMA_VISION.",
            )

        return _provider_result(
            normalized_task_type,
            normalized_ai_mode,
            PROVIDER_SKIP,
            "Local vision is disabled; vision_extract is skipped.",
        )

    raise ValueError(f"Unsupported task_type: {task_type}")


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


def _call_ollama_text_provider(
    provider: str,
    prompt: str,
    system_prompt: str | None,
    **kwargs,
) -> str:
    assert_local_ai_allowed()

    model = _provider_model_for_resolution(provider)
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages(prompt, system_prompt),
        "stream": False,
        "options": {
            "temperature": kwargs.get("temperature", 0),
        },
    }

    if kwargs.get("format") is not None:
        payload["format"] = kwargs["format"]

    with limit_llm_call(provider), limit_ollama_call(provider):
        response = requests.post(
            f"{_ollama_base_url()}/api/chat",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=_ollama_timeout(provider),
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

    return content


def _call_deepseek(
    prompt: str,
    system_prompt: str | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    assert_deepseek_allowed()

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

    with limit_llm_call("DEEPSEEK"):
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


def call_text_llm(
    task_type: str,
    prompt: str,
    system_prompt: str | None = None,
    ai_mode: str | None = None,
    **kwargs,
) -> str:
    effective_ai_mode = _resolve_effective_ai_mode(ai_mode)
    resolution = resolve_provider_for_task(task_type, effective_ai_mode)
    provider = resolution["provider"]
    model = resolution.get("model", "")
    provider_status = "success"
    input_chars = len(prompt or "") + len(system_prompt or "")
    started = time.time()

    json_output_task = task_type in {
        TASK_REQUIREMENT_ANALYSIS,
        TASK_CLARIFICATION_GENERATION,
    }

    if json_output_task and provider in {PROVIDER_OLLAMA_TEXT, PROVIDER_OLLAMA_COMPACT}:
        kwargs.setdefault("format", "json")
        kwargs.setdefault("temperature", 0)

    if json_output_task and provider == PROVIDER_DEEPSEEK:
        kwargs.setdefault("response_format", {"type": "json_object"})

    if provider == PROVIDER_SKIP:
        provider_status = "skipped"
        raise RuntimeError(
            resolution.get(
                "reason",
                "A configured provider is unavailable for the requested AI mode.",
            )
        )

    try:
        if provider == PROVIDER_DEEPSEEK:
            content, _ = _call_deepseek(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=kwargs.get("response_format"),
            )
        elif provider in {PROVIDER_OLLAMA_TEXT, PROVIDER_OLLAMA_COMPACT}:
            try:
                content = _call_ollama_text_provider(
                    provider=provider,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    **kwargs,
                )
            except Exception as error:
                provider_status = "error"
                if effective_ai_mode == AI_MODE_TEST_LOCAL_ONLY:
                    raise RuntimeError(
                        "Local AI is required in TEST_LOCAL_ONLY mode but is not available."
                    ) from error

                raise
        elif provider == PROVIDER_RULE_BASED:
            provider_status = "skipped"
            raise RuntimeError(
                f"Task {resolution['task_type']} resolved to RULE_BASED; "
                "no text LLM call is required."
            )
        else:
            provider_status = "error"
            raise RuntimeError(f"Unsupported text LLM provider: {provider}")

        duration_ms = int((time.time() - started) * 1000)
        response_preview = (content or "").replace("\n", " ").strip()[:500]
        logger.info(
            "Text LLM call job_id=%s task_type=%s ai_mode=%s provider=%s provider_status=%s model=%s "
            "input_chars=%s output_chars=%s duration_ms=%s response_preview=%s",
            get_current_job_id(),
            resolution["task_type"],
            resolution["ai_mode"],
            provider,
            provider_status,
            model,
            input_chars,
            len(content or ""),
            duration_ms,
            response_preview,
        )
        return content
    except Exception:
        duration_ms = int((time.time() - started) * 1000)
        logger.warning(
            "Text LLM call failed job_id=%s task_type=%s ai_mode=%s provider=%s provider_status=%s model=%s "
            "input_chars=%s duration_ms=%s response_preview=%s",
            get_current_job_id(),
            resolution["task_type"],
            resolution["ai_mode"],
            provider,
            provider_status,
            model,
            input_chars,
            duration_ms,
            ("" if provider_status == "skipped" else content[:500] if content else ""),
        )
        raise


def _call_LOCAL(
    provider: str,
    prompt: str,
    system_prompt: str | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    assert_local_ai_allowed()

    payload: dict[str, Any] = {
        "model": _provider_model(provider),
        "messages": _messages(prompt, system_prompt),
        "stream": False,
    }

    if response_format:
        payload["format"] = response_format

    with limit_llm_call(provider), limit_ollama_call(provider):
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
                "LLM router success job_id=%s task_type=%s provider=%s model=%s "
                "fallback_used=%s duration_seconds=%.2f input_chars=%s output_chars=%s",
                get_current_job_id(),
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
                "LLM router provider failed job_id=%s task_type=%s provider=%s model=%s "
                "duration_seconds=%.2f input_chars=%s error=%s",
                get_current_job_id(),
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
