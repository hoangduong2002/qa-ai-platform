import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from app.config.env_loader import load_project_env
from app.services.local_ai_config_service import (
    get_LOCAL_base_url,
    get_LOCAL_compact_model,
    get_LOCAL_text_model,
    get_LOCAL_vision_model,
    is_local_ai_enabled,
)
from app.services.portal_ai_mode_service import (
    assert_copilot_allowed,
    assert_deepseek_allowed,
    assert_local_ai_allowed,
    get_current_portal_ai_mode,
)
from app.services.portal_job_service import (
    get_current_job_id,
    limit_LOCAL_call,
    limit_llm_call,
)
from app.utils.ai_usage_logger import log_ai_usage


load_project_env()

logger = logging.getLogger(__name__)


TASK_REQUIREMENT_ANALYSIS = "requirement_analysis"
TASK_REQUIREMENT_SUMMARY = "requirement_summary"
TASK_TEST_STRUCTURE = "test_structure"
TASK_SCENARIO_GENERATION = "scenario_generation"
TASK_TESTCASE_GENERATION = "testcase_generation"
TASK_COVERAGE_REVIEW = "coverage_review"
TASK_SCENARIO_COVERAGE_REVIEW = "scenario_coverage_review"
TASK_SCENARIO_IMPROVEMENT = "scenario_improvement"
TASK_TESTCASE_IMPROVEMENT = "testcase_improvement"
TASK_FINAL_REVIEW = "final_review"
TASK_CLARIFICATION_GENERATION = "clarification_generation"
TASK_CHAT = "chat"
TASK_COMPACT_CONTEXT = "compact_context"
TASK_VISION_EXTRACT = "vision_extract"

AI_MODE_TEST_LOCAL_ONLY = "TEST_LOCAL_ONLY"
AI_MODE_PRODUCTION_HYBRID = "PRODUCTION_HYBRID"
AI_MODE_PRODUCTION_HYBRID_DEEPSEEK = "PRODUCTION_HYBRID_DEEPSEEK"
AI_MODE_PRODUCTION_HYBRID_COPILOT = "PRODUCTION_HYBRID_COPILOT"
AI_MODE_PRODUCTION_REMOTE_ONLY = "PRODUCTION_REMOTE_ONLY"
AI_MODE_DEEPSEEK_ONLY = "DEEPSEEK_ONLY"
AI_MODE_COPILOT_ONLY = "COPILOT_ONLY"
AI_MODE_NO_LLM = "NO_LLM"

PROVIDER_DEEPSEEK = "DEEPSEEK"
PROVIDER_COPILOT = "COPILOT"
PROVIDER_LOCAL_TEXT = "LOCAL_TEXT"
PROVIDER_LOCAL_COMPACT = "LOCAL_COMPACT"
PROVIDER_LOCAL_VISION = "LOCAL_VISION"
PROVIDER_RULE_BASED = "RULE_BASED"
PROVIDER_SKIP = "SKIP"

TEXT_REASONING_TASK_TYPES = {
    TASK_REQUIREMENT_ANALYSIS,
    TASK_REQUIREMENT_SUMMARY,
    TASK_TEST_STRUCTURE,
    TASK_SCENARIO_GENERATION,
    TASK_TESTCASE_GENERATION,
    TASK_COVERAGE_REVIEW,
    TASK_SCENARIO_COVERAGE_REVIEW,
    TASK_SCENARIO_IMPROVEMENT,
    TASK_TESTCASE_IMPROVEMENT,
    TASK_FINAL_REVIEW,
    TASK_CLARIFICATION_GENERATION,
    TASK_CHAT,
}
COMPACT_TASK_TYPES = {TASK_COMPACT_CONTEXT, "compact"}
VISION_TASK_TYPES = {TASK_VISION_EXTRACT, "vision"}
VALID_TASK_TYPES = TEXT_REASONING_TASK_TYPES | COMPACT_TASK_TYPES | VISION_TASK_TYPES
VALID_AI_MODES = {
    AI_MODE_TEST_LOCAL_ONLY,
    AI_MODE_PRODUCTION_HYBRID,
    AI_MODE_PRODUCTION_HYBRID_DEEPSEEK,
    AI_MODE_PRODUCTION_HYBRID_COPILOT,
    AI_MODE_PRODUCTION_REMOTE_ONLY,
    AI_MODE_DEEPSEEK_ONLY,
    AI_MODE_COPILOT_ONLY,
    AI_MODE_NO_LLM,
}
SUPPORTED_PROVIDERS = {
    PROVIDER_DEEPSEEK,
    PROVIDER_COPILOT,
    PROVIDER_LOCAL_TEXT,
    PROVIDER_LOCAL_COMPACT,
    PROVIDER_LOCAL_VISION,
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


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)

    if not value:
        return default

    return value.lower() in {"1", "true", "yes", "y", "on"}


def _normalize_ai_mode(ai_mode: str | None) -> str:
    normalized = (ai_mode or "").strip().upper()

    if normalized == AI_MODE_PRODUCTION_HYBRID:
        return AI_MODE_PRODUCTION_HYBRID_DEEPSEEK

    if normalized == AI_MODE_PRODUCTION_REMOTE_ONLY:
        return AI_MODE_DEEPSEEK_ONLY

    return normalized


def _resolve_effective_ai_mode(
    ai_mode: str | None,
    source_channel: str | None = None,
) -> str:
    normalized = _normalize_ai_mode(ai_mode)

    if normalized:
        return normalized

    if (source_channel or "").strip().lower() == "telegram":
        raise RuntimeError("Telegram ai_mode was not passed into generation state.")

    portal_mode = get_current_portal_ai_mode()

    if portal_mode and portal_mode.get("ai_mode"):
        return _normalize_ai_mode(str(portal_mode["ai_mode"]))

    return AI_MODE_NO_LLM


def _deepseek_available() -> bool:
    return bool(_env_str("DEEPSEEK_API_KEY")) and not _env_bool(
        "FORCE_DISABLE_DEEPSEEK",
        False,
    )


def _local_available() -> bool:
    return is_local_ai_enabled()


def _copilot_available() -> bool:
    return not _env_bool("FORCE_DISABLE_COPILOT", False)


def _deepseek_unavailable_reason(ai_mode: str) -> str:
    if _env_bool("FORCE_DISABLE_DEEPSEEK", False):
        return (
            f"AI provider is not available for AI_MODE={ai_mode}: "
            "DeepSeek is disabled by FORCE_DISABLE_DEEPSEEK=true."
        )

    if not _env_str("DEEPSEEK_API_KEY"):
        return (
            f"AI provider is not available for AI_MODE={ai_mode}: "
            "DEEPSEEK_API_KEY is missing."
        )

    return (
        f"AI provider is not available for AI_MODE={ai_mode}: "
        "DeepSeek is unavailable."
    )


def _local_unavailable_reason(ai_mode: str) -> str:
    if _env_bool("FORCE_DISABLE_LOCAL_AI", False):
        return (
            f"AI provider is not available for AI_MODE={ai_mode}: "
            "Local AI is disabled by FORCE_DISABLE_LOCAL_AI=true."
        )

    if not _env_str("LOCAL_BASE_URL"):
        return (
            f"AI provider is not available for AI_MODE={ai_mode}: "
            "LOCAL_BASE_URL is missing."
        )

    return (
        f"AI provider is not available for AI_MODE={ai_mode}: "
        "Local AI is unavailable."
    )


def _copilot_unavailable_reason(ai_mode: str) -> str:
    if _env_bool("FORCE_DISABLE_COPILOT", False):
        return "Copilot provider is disabled by FORCE_DISABLE_COPILOT=true."

    return (
        f"AI provider is not available for AI_MODE={ai_mode}: "
        "Copilot is unavailable."
    )


def _provider_model(provider: str) -> str:
    if provider == PROVIDER_DEEPSEEK:
        return _env_str("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if provider == PROVIDER_COPILOT:
        return _env_str("COPILOT_MODEL", "claude-sonnet-4.6")

    if provider == PROVIDER_LOCAL_TEXT:
        return get_LOCAL_text_model()

    if provider == PROVIDER_LOCAL_COMPACT:
        return get_LOCAL_compact_model()

    if provider == PROVIDER_LOCAL_VISION:
        return get_LOCAL_vision_model()

    if provider in {PROVIDER_RULE_BASED, PROVIDER_SKIP}:
        return ""

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _assert_deepseek_model_allowed(model: str) -> None:
    if "v4-pro" in (model or "").strip().lower() and not _env_bool(
        "ALLOW_DEEPSEEK_PRO",
        False,
    ):
        raise RuntimeError(
            "deepseek-v4-pro is disabled by cost guard. "
            "Set ALLOW_DEEPSEEK_PRO=true only if you intentionally want to use Pro."
        )


def _provider_timeout(provider: str) -> float:
    if provider == PROVIDER_DEEPSEEK:
        return _env_float("DEEPSEEK_TIMEOUT", 120)

    if provider == PROVIDER_COPILOT:
        return _env_float("COPILOT_TIMEOUT", 120)

    if provider == PROVIDER_LOCAL_COMPACT:
        return _env_float(
            "LOCAL_COMPACT_TIMEOUT",
            _env_float("LOCAL_TEXT_TIMEOUT", 180),
        )

    if provider == PROVIDER_LOCAL_VISION:
        return _env_float("LOCAL_VISION_TIMEOUT", 180)

    if provider == PROVIDER_LOCAL_TEXT:
        return _env_float("LOCAL_TEXT_TIMEOUT", 180)

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _health_check_timeout() -> float:
    return _env_float("LLM_HEALTH_CHECK_TIMEOUT", 30)


def _deepseek_chat_completions_url() -> str:
    configured = _env_str(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ).rstrip("/")

    if configured.endswith("/chat/completions"):
        return configured

    return f"{configured}/chat/completions"


def _copilot_chat_completions_url() -> str:
    return _env_str(
        "COPILOT_BASE_URL",
        "http://localhost:3100/v1/chat/completions",
    )


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
        "model": _provider_model(provider),
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
    normalized_ai_mode = _normalize_ai_mode(ai_mode)

    if normalized_task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Unsupported task_type: {task_type}")

    if normalized_ai_mode not in VALID_AI_MODES:
        raise ValueError(f"Unsupported ai_mode: {ai_mode}")

    deepseek_available = _deepseek_available()
    copilot_available = _copilot_available()
    local_available = _local_available()

    if normalized_task_type in TEXT_REASONING_TASK_TYPES:
        if normalized_ai_mode in {
            AI_MODE_PRODUCTION_HYBRID_DEEPSEEK,
            AI_MODE_DEEPSEEK_ONLY,
        }:
            if deepseek_available:
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
                _deepseek_unavailable_reason(normalized_ai_mode),
            )

        if normalized_ai_mode in {
            AI_MODE_PRODUCTION_HYBRID_COPILOT,
            AI_MODE_COPILOT_ONLY,
        }:
            if copilot_available:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_COPILOT,
                    f"{normalized_ai_mode} routes text/reasoning tasks to Copilot.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                _copilot_unavailable_reason(normalized_ai_mode),
            )

        if normalized_ai_mode == AI_MODE_TEST_LOCAL_ONLY:
            if local_available:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_LOCAL_TEXT,
                    "TEST_LOCAL_ONLY routes text/reasoning tasks to LOCAL_TEXT.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                _local_unavailable_reason(normalized_ai_mode),
            )

        if normalized_ai_mode == AI_MODE_NO_LLM:
            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                (
                    "AI mode is NO_LLM. This action requires an LLM. "
                    "Select TEST_LOCAL_ONLY, DEEPSEEK_ONLY, COPILOT_ONLY, "
                    "PRODUCTION_HYBRID_DEEPSEEK, or PRODUCTION_HYBRID_COPILOT."
                ),
            )

    if normalized_task_type in COMPACT_TASK_TYPES:
        if normalized_ai_mode in {
            AI_MODE_PRODUCTION_HYBRID_DEEPSEEK,
            AI_MODE_PRODUCTION_HYBRID_COPILOT,
            AI_MODE_TEST_LOCAL_ONLY,
        }:
            if local_available:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_LOCAL_COMPACT,
                    f"{normalized_ai_mode} routes compact_context to LOCAL_COMPACT.",
                )

            if normalized_ai_mode == AI_MODE_TEST_LOCAL_ONLY:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_SKIP,
                    _local_unavailable_reason(normalized_ai_mode),
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_RULE_BASED,
                "Local compact is unavailable; compact_context uses RULE_BASED.",
            )

        return _provider_result(
            normalized_task_type,
            normalized_ai_mode,
            PROVIDER_RULE_BASED,
            f"{normalized_ai_mode} routes compact_context to RULE_BASED.",
        )

    if normalized_task_type in VISION_TASK_TYPES:
        if normalized_ai_mode in {
            AI_MODE_PRODUCTION_HYBRID_DEEPSEEK,
            AI_MODE_PRODUCTION_HYBRID_COPILOT,
            AI_MODE_TEST_LOCAL_ONLY,
        }:
            if local_available:
                return _provider_result(
                    normalized_task_type,
                    normalized_ai_mode,
                    PROVIDER_LOCAL_VISION,
                    f"{normalized_ai_mode} routes vision_extract to LOCAL_VISION.",
                )

            return _provider_result(
                normalized_task_type,
                normalized_ai_mode,
                PROVIDER_SKIP,
                _local_unavailable_reason(normalized_ai_mode),
            )

        return _provider_result(
            normalized_task_type,
            normalized_ai_mode,
            PROVIDER_SKIP,
            f"{normalized_ai_mode} skips vision_extract.",
        )

    raise ValueError(f"Unsupported task_type: {task_type}")


def _messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": prompt})
    return messages


def _call_deepseek(
    prompt: str,
    system_prompt: str | None,
    response_format: Any | None,
    timeout: float | None = None,
) -> tuple[str, dict[str, Any]]:
    assert_deepseek_allowed()

    api_key = _env_str("DEEPSEEK_API_KEY")

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is missing for DeepSeek provider.")

    if _env_bool("FORCE_DISABLE_DEEPSEEK", False):
        raise RuntimeError("DeepSeek is disabled by FORCE_DISABLE_DEEPSEEK=true.")

    model = _provider_model(PROVIDER_DEEPSEEK)
    _assert_deepseek_model_allowed(model)

    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages(prompt, system_prompt),
        "temperature": 0,
    }

    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    elif response_format:
        payload["response_format"] = response_format

    with limit_llm_call(PROVIDER_DEEPSEEK):
        response = requests.post(
            _deepseek_chat_completions_url(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout or _provider_timeout(PROVIDER_DEEPSEEK),
        )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]

    if not content.strip():
        raise RuntimeError("DeepSeek returned an empty response.")

    return content, data


def _call_copilot(
    prompt: str,
    system_prompt: str | None = None,
    response_format: Any | None = None,
    timeout: float | None = None,
) -> tuple[str, dict[str, Any]]:
    if _env_bool("FORCE_DISABLE_COPILOT", False):
        raise RuntimeError(
            "Copilot provider is disabled by FORCE_DISABLE_COPILOT=true."
        )

    assert_copilot_allowed()

    headers = {
        "Content-Type": "application/json",
    }
    api_key = _env_str("COPILOT_API_KEY")

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": _provider_model(PROVIDER_COPILOT),
        "messages": _messages(prompt, system_prompt),
    }

    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    elif response_format:
        payload["response_format"] = response_format

    with limit_llm_call(PROVIDER_COPILOT):
        response = requests.post(
            _copilot_chat_completions_url(),
            headers=headers,
            json=payload,
            timeout=timeout or _provider_timeout(PROVIDER_COPILOT),
        )

    response.raise_for_status()
    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(
            "Copilot provider returned an invalid response: "
            "missing choices[0].message.content."
        ) from error

    if not str(content or "").strip():
        raise RuntimeError("Copilot returned an empty response.")

    return str(content), data


def _call_LOCAL(
    provider: str,
    prompt: str,
    system_prompt: str | None,
    response_format: Any | None,
    timeout: float | None = None,
    **kwargs,
) -> tuple[str, dict[str, Any]]:
    assert_local_ai_allowed()

    if _env_bool("FORCE_DISABLE_LOCAL_AI", False):
        raise RuntimeError("Local AI is disabled by FORCE_DISABLE_LOCAL_AI=true.")

    base_url = get_LOCAL_base_url()

    if not base_url:
        raise RuntimeError("LOCAL_BASE_URL is missing for local AI provider.")

    payload: dict[str, Any] = {
        "model": _provider_model(provider),
        "messages": _messages(prompt, system_prompt),
        "stream": False,
        "options": {
            "temperature": kwargs.get("temperature", 0),
        },
    }

    if response_format:
        payload["format"] = response_format

    with limit_llm_call(provider), limit_LOCAL_call(provider):
        response = requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout or _provider_timeout(provider),
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
    response_format: Any | None,
    **kwargs,
) -> tuple[str, dict[str, Any]]:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    timeout = kwargs.pop("timeout", None)

    if provider == PROVIDER_DEEPSEEK:
        return _call_deepseek(
            prompt,
            system_prompt,
            response_format,
            timeout=timeout,
        )

    if provider == PROVIDER_COPILOT:
        return _call_copilot(
            prompt,
            system_prompt,
            response_format,
            timeout=timeout,
        )

    return _call_LOCAL(
        provider,
        prompt,
        system_prompt,
        response_format,
        timeout=timeout,
        **kwargs,
    )


def _health_result(
    provider: str,
    model: str,
    status: str,
    duration_ms: int = 0,
    message: str = "",
    error: str = "",
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "provider": provider,
        "model": model,
        "status": status,
        "duration_ms": duration_ms,
        "message": message,
        "error": error,
    }

    result.update(extra)
    return result


def _friendly_health_error(error: Exception) -> str:
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return "Connection timed out while contacting provider."

    if isinstance(error, requests.exceptions.ReadTimeout):
        return "Provider did not respond before the read timeout."

    if isinstance(error, requests.exceptions.ConnectionError):
        return "Could not connect to provider endpoint."

    if isinstance(error, requests.exceptions.HTTPError):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code:
            return f"Provider returned HTTP {status_code}."
        return "Provider returned an HTTP error."

    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return f"Provider returned an invalid response format: {error}"

    if isinstance(error, RuntimeError):
        return str(error) or "Provider runtime error."

    return str(error) or "Provider health check failed."


def _friendly_local_health_error(error: Exception) -> str:
    if isinstance(error, requests.exceptions.ConnectionError):
        return "Could not connect to Ollama endpoint."

    if isinstance(error, requests.exceptions.ReadTimeout):
        return "Ollama connected but model did not respond before timeout."

    if isinstance(error, requests.exceptions.ConnectTimeout):
        return "Could not connect to Ollama endpoint before timeout."

    if isinstance(error, requests.exceptions.HTTPError):
        return "Ollama returned HTTP error."

    if isinstance(error, RuntimeError):
        return str(error) or "Ollama health check failed."

    return str(error) or "Ollama health check failed."


def _ollama_error_detail(error: Exception) -> str:
    response = getattr(error, "response", None)

    if response is None:
        return ""

    try:
        data = response.json()
    except Exception:
        text = getattr(response, "text", "")
        return str(text or "").strip()

    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or "").strip()

    return ""


def _is_ollama_model_not_found(error: Exception) -> bool:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    detail = _ollama_error_detail(error).lower()

    return (
        status_code == 404
        or "not found" in detail
        or "not available" in detail
        or "model" in detail and "does not exist" in detail
    )


def _friendly_local_vision_health_error(error: Exception, model: str) -> str:
    if isinstance(error, requests.exceptions.HTTPError) and _is_ollama_model_not_found(error):
        return (
            f"Ollama could not find model '{model}'. "
            f"Pull it with: ollama pull {model}"
        )

    return _friendly_local_health_error(error)


def _test_provider_health(provider: str, model: str) -> dict[str, Any]:
    prompt = "Reply with exactly: OK"
    system_prompt = "You are a health check endpoint. Reply only with OK."
    started = time.time()

    try:
        content, _ = _call_provider(
            provider=provider,
            prompt=prompt,
            system_prompt=system_prompt,
            response_format=None,
            timeout=_health_check_timeout(),
            temperature=0,
        )
        duration_ms = int((time.time() - started) * 1000)

        if not str(content or "").strip():
            return _health_result(
                provider=provider,
                model=model,
                status="FAILED",
                duration_ms=duration_ms,
                error="Provider returned an empty response.",
            )

        return _health_result(
            provider=provider,
            model=model,
            status="OK",
            duration_ms=duration_ms,
            message="Provider responded successfully.",
        )
    except Exception as error:
        duration_ms = int((time.time() - started) * 1000)
        logger.warning(
            "LLM health check failed provider=%s model=%s duration_ms=%s error=%s",
            provider,
            model,
            duration_ms,
            _friendly_health_error(error),
        )
        return _health_result(
            provider=provider,
            model=model,
            status="FAILED",
            duration_ms=duration_ms,
            error=_friendly_health_error(error),
        )


def _test_local_text_health(model: str, base_url: str) -> dict[str, Any]:
    provider = PROVIDER_LOCAL_TEXT
    resolved_url = f"{base_url.rstrip('/')}/api/chat"
    started = time.time()

    try:
        with limit_llm_call(provider), limit_LOCAL_call(provider):
            response = requests.post(
                resolved_url,
                headers={"Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly: OK",
                        },
                    ],
                    "stream": False,
                },
                timeout=_health_check_timeout(),
            )

        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content")
        duration_ms = int((time.time() - started) * 1000)

        if not str(content or "").strip():
            raise RuntimeError(
                "Ollama response did not contain message.content."
            )

        return _health_result(
            provider=provider,
            model=model,
            status="OK",
            duration_ms=duration_ms,
            message="Provider is working.",
            base_url=base_url,
            resolved_url=resolved_url,
            exception_type="",
        )
    except Exception as error:
        duration_ms = int((time.time() - started) * 1000)
        exception_type = type(error).__name__
        friendly_error = _friendly_local_health_error(error)
        logger.warning(
            "LOCAL_TEXT health check failed provider=%s model=%s base_url=%s "
            "resolved_url=%s exception_type=%s duration_ms=%s error=%s",
            provider,
            model,
            base_url,
            resolved_url,
            exception_type,
            duration_ms,
            friendly_error,
        )
        return _health_result(
            provider=provider,
            model=model,
            status="FAILED",
            duration_ms=duration_ms,
            error=friendly_error,
            base_url=base_url,
            resolved_url=resolved_url,
            exception_type=exception_type,
        )


def _test_local_vision_health(model: str, base_url: str) -> dict[str, Any]:
    provider = PROVIDER_LOCAL_VISION
    resolved_url = f"{base_url.rstrip('/')}/api/show"
    started = time.time()

    try:
        with limit_llm_call(provider), limit_LOCAL_call(provider):
            response = requests.post(
                resolved_url,
                headers={"Content-Type": "application/json"},
                json={"model": model},
                timeout=_health_check_timeout(),
            )

        response.raise_for_status()
        duration_ms = int((time.time() - started) * 1000)

        return _health_result(
            provider=provider,
            model=model,
            status="OK",
            duration_ms=duration_ms,
            message="Vision model is available in Ollama. Vision inference was not tested.",
            base_url=base_url,
            resolved_url=resolved_url,
            exception_type="",
        )
    except Exception as error:
        duration_ms = int((time.time() - started) * 1000)
        exception_type = type(error).__name__
        friendly_error = _friendly_local_vision_health_error(error, model)
        message = (
            "Vision model is not available in Ollama."
            if _is_ollama_model_not_found(error)
            else "Vision model availability check failed."
        )
        logger.warning(
            "LOCAL_VISION health check failed provider=%s model=%s base_url=%s "
            "resolved_url=%s exception_type=%s duration_ms=%s error=%s",
            provider,
            model,
            base_url,
            resolved_url,
            exception_type,
            duration_ms,
            friendly_error,
        )
        return _health_result(
            provider=provider,
            model=model,
            status="FAILED",
            duration_ms=duration_ms,
            message=message,
            error=friendly_error,
            base_url=base_url,
            resolved_url=resolved_url,
            exception_type=exception_type,
        )


def test_all_llm_providers() -> dict[str, Any]:
    started = time.time()
    results = []

    deepseek_model = _provider_model(PROVIDER_DEEPSEEK)
    if _env_bool("FORCE_DISABLE_DEEPSEEK", False):
        results.append(
            _health_result(
                PROVIDER_DEEPSEEK,
                deepseek_model,
                "DISABLED",
                message="DeepSeek is disabled by FORCE_DISABLE_DEEPSEEK=true.",
            )
        )
    elif not _env_str("DEEPSEEK_API_KEY"):
        results.append(
            _health_result(
                PROVIDER_DEEPSEEK,
                deepseek_model,
                "SKIPPED",
                message="DEEPSEEK_API_KEY is missing.",
            )
        )
    else:
        results.append(_test_provider_health(PROVIDER_DEEPSEEK, deepseek_model))

    copilot_model = _env_str("COPILOT_MODEL")
    copilot_base_url = _env_str("COPILOT_BASE_URL")
    if _env_bool("FORCE_DISABLE_COPILOT", False):
        results.append(
            _health_result(
                PROVIDER_COPILOT,
                copilot_model,
                "DISABLED",
                message="Copilot provider is disabled by FORCE_DISABLE_COPILOT=true.",
            )
        )
    elif not copilot_base_url:
        results.append(
            _health_result(
                PROVIDER_COPILOT,
                copilot_model,
                "SKIPPED",
                message="COPILOT_BASE_URL is missing.",
            )
        )
    elif not copilot_model:
        results.append(
            _health_result(
                PROVIDER_COPILOT,
                copilot_model,
                "SKIPPED",
                message="COPILOT_MODEL is missing.",
            )
        )
    else:
        results.append(_test_provider_health(PROVIDER_COPILOT, copilot_model))

    local_text_model = _env_str("LOCAL_TEXT_MODEL")
    local_base_url = _env_str("LOCAL_BASE_URL")
    if _env_bool("FORCE_DISABLE_LOCAL_AI", False):
        results.append(
            _health_result(
                PROVIDER_LOCAL_TEXT,
                local_text_model,
                "DISABLED",
                message="Local AI is disabled by FORCE_DISABLE_LOCAL_AI=true.",
            )
        )
    elif not local_base_url:
        results.append(
            _health_result(
                PROVIDER_LOCAL_TEXT,
                local_text_model,
                "SKIPPED",
                message="LOCAL_BASE_URL is missing.",
            )
        )
    elif not local_text_model:
        results.append(
            _health_result(
                PROVIDER_LOCAL_TEXT,
                local_text_model,
                "SKIPPED",
                message="LOCAL_TEXT_MODEL is missing.",
            )
        )
    else:
        results.append(
            _test_local_text_health(
                model=local_text_model,
                base_url=local_base_url,
            )
        )

    local_vision_model = _env_str("LOCAL_VISION_MODEL")
    if _env_bool("FORCE_DISABLE_LOCAL_AI", False):
        results.append(
            _health_result(
                PROVIDER_LOCAL_VISION,
                local_vision_model,
                "DISABLED",
                message="Local AI is disabled by FORCE_DISABLE_LOCAL_AI=true.",
            )
        )
    elif not local_base_url:
        results.append(
            _health_result(
                PROVIDER_LOCAL_VISION,
                local_vision_model,
                "SKIPPED",
                message="LOCAL_BASE_URL is missing.",
            )
        )
    elif not local_vision_model:
        results.append(
            _health_result(
                PROVIDER_LOCAL_VISION,
                local_vision_model,
                "SKIPPED",
                message="LOCAL_VISION_MODEL is missing.",
            )
        )
    else:
        results.append(
            _test_local_vision_health(
                model=local_vision_model,
                base_url=local_base_url,
            )
        )

    return {
        "ok": not any(result.get("status") == "FAILED" for result in results),
        "duration_ms": int((time.time() - started) * 1000),
        "results": results,
    }


def _raise_if_non_text_provider(resolution: dict[str, str]) -> None:
    provider = resolution["provider"]

    if provider == PROVIDER_SKIP:
        raise RuntimeError(
            resolution.get(
                "reason",
                "A configured provider is unavailable for the requested AI mode.",
            )
        )

    if provider == PROVIDER_RULE_BASED:
        raise RuntimeError(
            f"Task {resolution['task_type']} resolved to RULE_BASED; "
            "no text LLM call is required."
        )


def call_text_llm(
    task_type: str,
    prompt: str,
    system_prompt: str | None = None,
    ai_mode: str | None = None,
    source_channel: str | None = None,
    **kwargs,
) -> str:
    effective_ai_mode = _resolve_effective_ai_mode(
        ai_mode,
        source_channel=source_channel,
    )
    resolution = resolve_provider_for_task(task_type, effective_ai_mode)
    provider = resolution["provider"]
    model = resolution.get("model", "")
    provider_status = "success"
    input_chars = len(prompt or "") + len(system_prompt or "")
    started = time.time()
    content = ""
    ticket_id = str(kwargs.get("ticket_id") or "")
    node_name = str(kwargs.get("node_name") or "")

    _raise_if_non_text_provider(resolution)

    json_output_task = task_type in {
        TASK_REQUIREMENT_ANALYSIS,
        TASK_CLARIFICATION_GENERATION,
    }

    if json_output_task and provider in {
        PROVIDER_LOCAL_TEXT,
        PROVIDER_LOCAL_COMPACT,
    }:
        kwargs.setdefault("response_format", "json")
        kwargs.setdefault("temperature", 0)

    if json_output_task and provider in {PROVIDER_DEEPSEEK, PROVIDER_COPILOT}:
        kwargs.setdefault("response_format", {"type": "json_object"})

    try:
        content, raw = _call_provider(
            provider=provider,
            prompt=prompt,
            system_prompt=system_prompt,
            response_format=kwargs.get("response_format"),
            temperature=kwargs.get("temperature", 0),
        )

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
        log_ai_usage(
            ticket_id=ticket_id,
            node_name=node_name,
            model=model,
            provider=provider,
            prompt=(system_prompt or "") + (prompt or ""),
            response=content,
            duration_ms=duration_ms,
            ai_mode=resolution["ai_mode"],
            task_type=resolution["task_type"],
            source_channel=source_channel or "",
            job_id=get_current_job_id(),
            status="success",
            raw_usage=raw,
        )
        return content
    except Exception as error:
        duration_ms = int((time.time() - started) * 1000)
        provider_status = "error"
        logger.warning(
            "Text LLM call failed job_id=%s task_type=%s ai_mode=%s provider=%s provider_status=%s model=%s "
            "input_chars=%s duration_ms=%s",
            get_current_job_id(),
            resolution["task_type"],
            resolution["ai_mode"],
            provider,
            provider_status,
            model,
            input_chars,
            duration_ms,
        )
        log_ai_usage(
            ticket_id=ticket_id,
            node_name=node_name,
            model=model,
            provider=provider,
            prompt=(system_prompt or "") + (prompt or ""),
            response=content,
            duration_ms=duration_ms,
            ai_mode=resolution["ai_mode"],
            task_type=resolution["task_type"],
            source_channel=source_channel or "",
            job_id=get_current_job_id(),
            status="error",
            error_type=type(error).__name__,
        )
        raise


def call_llm_with_fallback(
    task_type: str,
    prompt: str,
    system_prompt: str | None = None,
    response_format: Any | None = None,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> LLMRouterResponse:
    effective_ai_mode = _resolve_effective_ai_mode(
        ai_mode,
        source_channel=source_channel,
    )
    resolution = resolve_provider_for_task(task_type, effective_ai_mode)
    provider = resolution["provider"]
    model = resolution.get("model", "")
    input_chars = len(prompt or "") + len(system_prompt or "")
    started = time.time()

    _raise_if_non_text_provider(resolution)

    try:
        content, raw = _call_provider(
            provider=provider,
            prompt=prompt,
            system_prompt=system_prompt,
            response_format=response_format,
        )
        duration = time.time() - started
    except Exception as error:
        duration_ms = int((time.time() - started) * 1000)
        log_ai_usage(
            ticket_id="",
            node_name="",
            model=model,
            provider=provider,
            prompt=(system_prompt or "") + (prompt or ""),
            response="",
            duration_ms=duration_ms,
            ai_mode=resolution["ai_mode"],
            task_type=resolution["task_type"],
            source_channel=source_channel or "",
            job_id=get_current_job_id(),
            status="error",
            error_type=type(error).__name__,
        )
        raise

    logger.info(
        "LLM router success job_id=%s task_type=%s ai_mode=%s provider=%s model=%s "
        "fallback_used=%s duration_seconds=%.2f input_chars=%s output_chars=%s",
        get_current_job_id(),
        resolution["task_type"],
        resolution["ai_mode"],
        provider,
        model,
        False,
        duration,
        input_chars,
        len(content or ""),
    )
    log_ai_usage(
        ticket_id="",
        node_name="",
        model=model,
        provider=provider,
        prompt=(system_prompt or "") + (prompt or ""),
        response=content,
        duration_ms=int(duration * 1000),
        ai_mode=resolution["ai_mode"],
        task_type=resolution["task_type"],
        source_channel=source_channel or "",
        job_id=get_current_job_id(),
        status="success",
        raw_usage=raw,
    )

    return LLMRouterResponse(
        content=content,
        provider=provider,
        model=model,
        fallback_used=False,
        duration_seconds=duration,
        input_chars=input_chars,
        output_chars=len(content or ""),
        raw=raw,
    )
