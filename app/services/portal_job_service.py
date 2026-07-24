import asyncio
import errno
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from app.config.env_loader import PROJECT_ROOT
from app.services.portal_ai_mode_service import (
    reset_portal_ai_mode,
    set_portal_ai_mode_context,
)
from app.services.ai_provider_error_service import format_provider_error


logger = logging.getLogger(__name__)

RUNTIME_PORTAL_JOBS_DIR = (PROJECT_ROOT / "runtime" / "portal_jobs").resolve()

TICKET_BUSY_MESSAGE = "This ticket is already being processed."
JOB_LIMIT_MESSAGE = "The portal is currently processing the maximum number of jobs. Please try again shortly."
LLM_LIMIT_MESSAGE = "The portal is currently processing the maximum number of LLM calls. Please try again shortly."
LOCAL_LIMIT_MESSAGE = "The local AI server is currently busy. Please try again shortly."

# Provider safety messages
NO_LLM_BLOCKED_MESSAGE = (
    "AI mode is NO_LLM. This action requires an LLM. "
    "Select TEST_LOCAL_ONLY, PRODUCTION_HYBRID_DEEPSEEK, "
    "PRODUCTION_HYBRID_COPILOT, DEEPSEEK_ONLY, or COPILOT_ONLY."
)
TEST_LOCAL_ONLY_UNAVAILABLE_MESSAGE = (
    "AI mode is TEST_LOCAL_ONLY but the local AI provider is not available. "
    "Check that LOCAL_BASE_URL is set and FORCE_DISABLE_LOCAL_AI=false."
)
FALLBACK_TO_DEEPSEEK_BLOCKED_MESSAGE = (
    "AI mode is TEST_LOCAL_ONLY; falling back to DeepSeek is not allowed. "
    "Ensure the local AI provider is running."
)

_job_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "portal_job_context",
    default=None,
)

_ticket_locks_guard = threading.Lock()
_ticket_locks: dict[str, threading.Lock] = {}
_job_metadata_lock = threading.RLock()
_generation_semaphore: threading.BoundedSemaphore | None = None
_generation_semaphore_size: int | None = None
_llm_semaphores_guard = threading.Lock()
_llm_semaphores: dict[str, threading.BoundedSemaphore] = {}
_llm_semaphore_sizes: dict[str, int] = {}
_llm_active_calls: dict[str, int] = {}
_LOCAL_semaphore: threading.BoundedSemaphore | None = None
_LOCAL_semaphore_size: int | None = None


class PortalJobBusyError(RuntimeError):
    pass


class PortalConcurrencyError(RuntimeError):
    pass


class PortalJobMetadataInvalidError(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default

    return max(value, 1)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default

    return max(value, 0.0)


def _get_semaphore(
    name: str,
    default: int,
    current: threading.BoundedSemaphore | None,
    current_size: int | None,
) -> tuple[threading.BoundedSemaphore, int]:
    size = _env_int(name, default)

    if current is None or current_size != size:
        return threading.BoundedSemaphore(size), size

    return current, current_size


def _generation_limit() -> threading.BoundedSemaphore:
    global _generation_semaphore, _generation_semaphore_size

    _generation_semaphore, _generation_semaphore_size = _get_semaphore(
        "MAX_PARALLEL_GENERATION_JOBS",
        2,
        _generation_semaphore,
        _generation_semaphore_size,
    )
    return _generation_semaphore


def _llm_limit() -> threading.BoundedSemaphore:
    semaphore, _ = _provider_llm_limit("")
    return semaphore


def _normalize_provider_key(provider: str = "") -> str:
    normalized = (provider or "").strip().upper()

    if normalized == "DEEPSEEK":
        return "DEEPSEEK"

    if normalized == "COPILOT":
        return "COPILOT"

    if normalized.startswith("LOCAL"):
        return "LOCAL"

    return "GLOBAL"


def _provider_llm_env(provider_key: str) -> tuple[str, int]:
    if provider_key == "DEEPSEEK":
        return "MAX_CONCURRENT_DEEPSEEK_CALLS", 2

    if provider_key == "COPILOT":
        return "MAX_CONCURRENT_COPILOT_CALLS", 2

    if provider_key == "LOCAL":
        return "MAX_CONCURRENT_LOCAL_CALLS", 1

    return "MAX_CONCURRENT_LLM_CALLS", 2


def _provider_llm_limit(provider: str) -> tuple[threading.BoundedSemaphore, int]:
    provider_key = _normalize_provider_key(provider)
    env_name, default = _provider_llm_env(provider_key)
    size = _env_int(env_name, default)

    with _llm_semaphores_guard:
        semaphore = _llm_semaphores.get(provider_key)

        if semaphore is None or _llm_semaphore_sizes.get(provider_key) != size:
            semaphore = threading.BoundedSemaphore(size)
            _llm_semaphores[provider_key] = semaphore
            _llm_semaphore_sizes[provider_key] = size
            _llm_active_calls[provider_key] = 0

        return semaphore, size


def _active_llm_calls(provider: str) -> int:
    provider_key = _normalize_provider_key(provider)

    with _llm_semaphores_guard:
        return _llm_active_calls.get(provider_key, 0)


def _increment_active_llm_calls(provider: str) -> int:
    provider_key = _normalize_provider_key(provider)

    with _llm_semaphores_guard:
        active = _llm_active_calls.get(provider_key, 0) + 1
        _llm_active_calls[provider_key] = active
        return active


def _decrement_active_llm_calls(provider: str) -> int:
    provider_key = _normalize_provider_key(provider)

    with _llm_semaphores_guard:
        active = max(_llm_active_calls.get(provider_key, 0) - 1, 0)
        _llm_active_calls[provider_key] = active
        return active


def _LOCAL_limit() -> threading.BoundedSemaphore:
    global _LOCAL_semaphore, _LOCAL_semaphore_size

    _LOCAL_semaphore, _LOCAL_semaphore_size = _get_semaphore(
        "MAX_CONCURRENT_LOCAL_CALLS",
        1,
        _LOCAL_semaphore,
        _LOCAL_semaphore_size,
    )
    return _LOCAL_semaphore


def create_job_id() -> str:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    return f"job_{timestamp}_{uuid.uuid4().hex[:8]}"


def get_current_job_context() -> dict[str, Any] | None:
    return _job_context.get()


def get_current_job_id() -> str:
    context = _job_context.get()
    if not context:
        return ""

    return str(context.get("job_id") or "")


def get_job_metadata_path(job_id: str) -> Path:
    clean_job_id = str(job_id or "").strip()
    if not clean_job_id or Path(clean_job_id).name != clean_job_id:
        raise ValueError("Invalid portal job ID.")
    return RUNTIME_PORTAL_JOBS_DIR / f"{clean_job_id}_metadata.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write formatted JSON through a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    temporary_path: Path | None = None
    file_descriptor: int | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            file_descriptor = None
            stream.write(serialized)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                    raise
        for replace_attempt in range(1, 4):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                if replace_attempt == 3:
                    raise
                time.sleep(0.01 * replace_attempt)
        temporary_path = None
    except Exception:
        logger.exception("Atomic portal job metadata write failed. path=%s", path)
        raise
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Unable to clean temporary portal job metadata file. path=%s",
                    temporary_path,
                    exc_info=True,
                )


def _read_job_metadata_unlocked(job_id: str) -> dict[str, Any]:
    path = get_job_metadata_path(job_id)
    exists = path.exists()
    logger.info(
        "Portal job metadata lookup. job_id=%s path=%s exists=%s cwd=%s",
        job_id,
        path,
        exists,
        Path.cwd(),
    )

    if not exists:
        raise FileNotFoundError(f"Portal job metadata does not exist: {path}")

    retry_delays = (0.025, 0.05)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            raw_metadata = path.read_text(encoding="utf-8")
        except PermissionError:
            logger.exception(
                "Portal job metadata permission error. job_id=%s path=%s "
                "attempt=%s cwd=%s",
                job_id,
                path,
                attempt,
                Path.cwd(),
            )
            raise
        except OSError:
            logger.exception(
                "Portal job metadata read error. job_id=%s path=%s attempt=%s cwd=%s",
                job_id,
                path,
                attempt,
                Path.cwd(),
            )
            raise

        try:
            metadata = json.loads(raw_metadata)
            if not isinstance(metadata, dict):
                raise ValueError("metadata JSON root is not an object")
            return metadata
        except (json.JSONDecodeError, ValueError) as error:
            last_error = error
            file_size = len(raw_metadata.encode("utf-8"))
            if attempt < 3:
                logger.warning(
                    "Invalid portal job metadata; retrying. job_id=%s path=%s "
                    "attempt=%s file_size=%s cwd=%s exception_type=%s",
                    job_id,
                    path,
                    attempt,
                    file_size,
                    Path.cwd(),
                    type(error).__name__,
                )
                time.sleep(retry_delays[attempt - 1])
                continue
            logger.error(
                "Portal job metadata remains invalid after retries. job_id=%s "
                "path=%s attempt=%s file_size=%s cwd=%s exception_type=%s",
                job_id,
                path,
                attempt,
                file_size,
                Path.cwd(),
                type(error).__name__,
            )

    raise PortalJobMetadataInvalidError(
        "Portal job metadata remains invalid after bounded retries."
    ) from last_error


def _read_job_metadata(job_id: str) -> dict[str, Any]:
    with _job_metadata_lock:
        return _read_job_metadata_unlocked(job_id)


def check_provider_safety(ai_mode_context: dict[str, Any] | None) -> None:
    """Validate provider safety rules before dispatching a job.

    Raises ``RuntimeError`` when the action is unsafe for the current AI mode.
    Does **not** call any LLM.
    """
    if not ai_mode_context:
        return

    ai_mode = str(ai_mode_context.get("ai_mode") or "").strip().upper()

    # NO_LLM blocks everything
    if ai_mode == "NO_LLM":
        raise RuntimeError(NO_LLM_BLOCKED_MESSAGE)

    local_enabled = bool(ai_mode_context.get("local_ai_enabled", False))
    server_local_enabled = bool(ai_mode_context.get("server_local_ai_enabled", False))
    deepseek_enabled = bool(ai_mode_context.get("deepseek_enabled", False))

    # TEST_LOCAL_ONLY: local must be available, never fallback to DeepSeek
    if ai_mode == "TEST_LOCAL_ONLY":
        if not local_enabled or not server_local_enabled:
            raise RuntimeError(TEST_LOCAL_ONLY_UNAVAILABLE_MESSAGE)
        if deepseek_enabled:
            logger.info(
                "TEST_LOCAL_ONLY mode: DeepSeek is enabled but will not be "
                "used as a fallback for this action."
            )


def create_job(
    *,
    ticket_id: str,
    action: str,
    ai_mode_context: dict[str, Any] | None,
) -> str:
    job_id = create_job_id()
    context = {
        "job_id": job_id,
        "ticket_id": ticket_id,
        "action": action,
        "ai_mode": (ai_mode_context or {}).get("ai_mode"),
        "production_mode": (ai_mode_context or {}).get("production_mode"),
        "local_ai_enabled": (ai_mode_context or {}).get("local_ai_enabled"),
        "status": "PENDING",
        "current_step": "Queued",
        "step_label": "Queued",
        "message": "Job has been queued and will start shortly.",
        "detail": "Job has been queued and will start shortly.",
        "progress_percent": 0,
        "started_at": "",
        "ended_at": "",
        "duration_ms": 0,
        "error": "",
    }
    _update_job_metadata(context)
    return job_id


def update_job_progress(
    current_step: str | None = None,
    message: str | None = None,
    step_label: str | None = None,
    detail: str | None = None,
    progress_percent: int | None = None,
) -> None:
    context = _job_context.get()
    if not context:
        return

    updates: dict[str, Any] = {}
    if current_step is not None:
        updates["current_step"] = current_step
        updates["step_label"] = current_step

    if step_label is not None:
        updates["step_label"] = step_label
        updates["current_step"] = step_label

    if message is not None:
        updates["message"] = message
        updates["detail"] = message

    if detail is not None:
        updates["detail"] = detail
        updates["message"] = detail

    if progress_percent is not None:
        updates["progress_percent"] = max(0, min(100, int(progress_percent)))

    _update_job_metadata(context, updates)


def get_job_status(job_id: str) -> dict[str, Any]:
    return _read_job_metadata(job_id)


def _ticket_lock(ticket_id: str) -> threading.Lock:
    with _ticket_locks_guard:
        lock = _ticket_locks.get(ticket_id)

        if lock is None:
            lock = threading.Lock()
            _ticket_locks[ticket_id] = lock

        return lock


def _metadata_from_context(context: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(context.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("Portal job metadata requires a ticket_id.")
    return {
        "job_id": context.get("job_id"),
        "ticket_id": ticket_id,
        "action": context.get("action"),
        "ai_mode": context.get("ai_mode"),
        "production_mode": context.get("production_mode"),
        "local_ai_enabled": context.get("local_ai_enabled"),
        "status": context.get("status"),
        "current_step": context.get("current_step", ""),
        "step_label": context.get("step_label") or context.get("current_step", ""),
        "message": context.get("message", ""),
        "detail": context.get("detail") or context.get("message", ""),
        "progress_percent": context.get("progress_percent", 0),
        "started_at": context.get("started_at"),
        "ended_at": context.get("ended_at"),
        "duration_ms": context.get("duration_ms"),
        "error": context.get("error", ""),
        "source": "web_portal",
    }


def _write_job_metadata_unlocked(context: dict[str, Any]) -> None:
    metadata = _metadata_from_context(context)
    ticket_id = metadata["ticket_id"]
    action = str(context.get("action") or "")

    # For create_requirement_from_jira, write metadata to a staging location
    # so that the requirement folder is not created prematurely.
    # Premature folder creation causes requirement_exists() to return True
    # and the Jira loader gets skipped.
    runtime_path = get_job_metadata_path(str(context.get("job_id") or ""))
    _write_json_atomic(runtime_path, metadata)

    if action == "create_requirement_from_jira":
        jobs_dir = Path("requirements") / "_jobs" / ticket_id
        _write_json_atomic(
            jobs_dir / f"{context.get('job_id')}_metadata.json",
            metadata,
        )
        _write_json_atomic(jobs_dir / "latest_job_metadata.json", metadata)
        logger.info(
            "Portal job metadata written to staging path. "
            "job_id=%s ticket_id=%s action=%s path=%s",
            context.get("job_id"),
            ticket_id,
            action,
            jobs_dir,
        )
    else:
        analysis_dir = Path("requirements") / ticket_id / "analysis"
        _write_json_atomic(
            analysis_dir / f"{context.get('job_id')}_metadata.json",
            metadata,
        )
        _write_json_atomic(analysis_dir / "latest_job_metadata.json", metadata)


def _write_job_metadata(context: dict[str, Any]) -> None:
    """Backward-compatible wrapper around the canonical update function."""
    _update_job_metadata(context)


def _update_job_metadata(
    context: dict[str, Any],
    updates: dict[str, Any] | None = None,
) -> None:
    """Serialize an in-process context update and all of its metadata writes."""
    with _job_metadata_lock:
        if updates:
            context.update(updates)
        _write_job_metadata_unlocked(context)


def _copy_job_metadata_to_requirement(context: dict[str, Any]) -> None:
    """Copy job metadata from staging path to the requirement's analysis folder.

    Only call after the requirement has been fully created.
    """
    with _job_metadata_lock:
        metadata = _metadata_from_context(context)
        ticket_id = metadata["ticket_id"]
        analysis_dir = Path("requirements") / ticket_id / "analysis"
        jobs_dir = Path("requirements") / "_jobs" / ticket_id
        if not jobs_dir.exists():
            return
        _write_json_atomic(
            analysis_dir / f"{context.get('job_id')}_metadata.json",
            metadata,
        )
        # Diagnostic snapshot only; status lookup always uses the runtime
        # job-specific file returned by get_job_metadata_path().
        _write_json_atomic(analysis_dir / "latest_job_metadata.json", metadata)

    logger.info(
        "Portal job metadata copied to requirement analysis. "
        "job_id=%s ticket_id=%s path=%s",
        context.get("job_id"),
        ticket_id,
        analysis_dir,
    )


async def run_portal_ticket_job(
    *,
    ticket_id: str,
    action: str,
    ai_mode_context: dict[str, Any] | None,
    job_callable: Callable[[], Any],
    job_id: str | None = None,
) -> Any:
    job_id = job_id or create_job_id()
    ticket_lock = _ticket_lock(ticket_id)

    if not ticket_lock.acquire(blocking=False):
        logger.warning(
            "Portal job rejected because ticket is busy. ticket_id=%s action=%s job_id=%s",
            ticket_id,
            action,
            job_id,
        )
        raise PortalJobBusyError(TICKET_BUSY_MESSAGE)

    generation_semaphore = _generation_limit()

    if not generation_semaphore.acquire(blocking=False):
        ticket_lock.release()
        logger.warning(
            "Portal job rejected because global generation limit is full. ticket_id=%s action=%s job_id=%s",
            ticket_id,
            action,
            job_id,
        )
        raise PortalConcurrencyError(JOB_LIMIT_MESSAGE)

    started = time.time()
    context = {
        "job_id": job_id,
        "ticket_id": ticket_id,
        "action": action,
        "ai_mode": (ai_mode_context or {}).get("ai_mode"),
        "production_mode": (ai_mode_context or {}).get("production_mode"),
        "local_ai_enabled": (ai_mode_context or {}).get("local_ai_enabled"),
        "status": "RUNNING",
        "current_step": "Starting",
        "step_label": "Starting",
        "message": "Starting job.",
        "detail": "Starting job.",
        "progress_percent": 5,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    token = _job_context.set(context)
    ai_mode_token = set_portal_ai_mode_context(ai_mode_context)
    _update_job_metadata(context)

    logger.info(
        "Portal job started job_id=%s ticket_id=%s action=%s ai_mode=%s",
        job_id,
        ticket_id,
        action,
        context.get("ai_mode"),
    )

    try:
        result = job_callable()

        if asyncio.iscoroutine(result):
            result = await result

        _update_job_metadata(
            context,
            {
                "status": "SUCCEEDED",
                "current_step": "Complete",
                "step_label": "Complete",
                "message": "Job completed.",
                "detail": "Job completed.",
                "progress_percent": 100,
            },
        )

        # After a successful create_requirement_from_jira, the requirement
        # folder should now be complete.  Copy job metadata into the
        # requirement's analysis/ directory so it is visible alongside the
        # sanitized requirement.
        if action == "create_requirement_from_jira":
            _copy_job_metadata_to_requirement(context)

        return result
    except Exception as error:
        formatted_error = format_provider_error(
            error=error,
            ai_mode=context.get("ai_mode"),
            source_channel="portal",
        )
        _update_job_metadata(
            context,
            {
                "status": "FAILED",
                "error": formatted_error,
                "current_step": "Failed",
                "step_label": "Failed",
                "message": formatted_error,
                "detail": formatted_error,
            },
        )
        logger.exception(
            "Portal job failed job_id=%s ticket_id=%s action=%s",
            job_id,
            ticket_id,
            action,
        )
        raise
    finally:
        _update_job_metadata(
            context,
            {
                "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "duration_ms": int((time.time() - started) * 1000),
            },
        )
        reset_portal_ai_mode(ai_mode_token)
        logger.info(
            "Portal job finished job_id=%s ticket_id=%s action=%s status=%s duration_ms=%s",
            job_id,
            ticket_id,
            action,
            context.get("status"),
            context.get("duration_ms"),
        )
        _job_context.reset(token)
        generation_semaphore.release()
        ticket_lock.release()


@contextmanager
def limit_llm_call(provider: str = ""):
    semaphore, max_llm_calls = _provider_llm_limit(provider)
    wait_timeout = _env_float("LLM_CONCURRENCY_WAIT_TIMEOUT", 300)
    active_before_wait = _active_llm_calls(provider)

    logger.info(
        "LLM concurrency guard waiting job_id=%s provider=%s active_llm_calls=%s "
        "max_llm_calls=%s wait_timeout=%s",
        get_current_job_id(),
        provider,
        active_before_wait,
        max_llm_calls,
        wait_timeout,
    )

    if not semaphore.acquire(blocking=True, timeout=wait_timeout):
        logger.warning(
            "LLM concurrency wait timed out job_id=%s provider=%s active_llm_calls=%s "
            "max_llm_calls=%s wait_timeout=%s",
            get_current_job_id(),
            provider,
            _active_llm_calls(provider),
            max_llm_calls,
            wait_timeout,
        )
        raise PortalConcurrencyError(
            "The portal is still processing the maximum number of LLM calls "
            f"after waiting {int(wait_timeout)} seconds. Please try again shortly."
        )

    try:
        active_after_acquire = _increment_active_llm_calls(provider)
        logger.info(
            "LLM concurrency slot acquired job_id=%s provider=%s active_llm_calls=%s "
            "max_llm_calls=%s wait_timeout=%s",
            get_current_job_id(),
            provider,
            active_after_acquire,
            max_llm_calls,
            wait_timeout,
        )
        yield
    finally:
        active_after_release = _decrement_active_llm_calls(provider)
        semaphore.release()
        logger.info(
            "LLM concurrency slot released job_id=%s provider=%s active_llm_calls=%s "
            "max_llm_calls=%s wait_timeout=%s",
            get_current_job_id(),
            provider,
            active_after_release,
            max_llm_calls,
            wait_timeout,
        )


@contextmanager
def limit_LOCAL_call(provider: str = ""):
    semaphore = _LOCAL_limit()

    if not semaphore.acquire(blocking=False):
        logger.warning(
            "LOCAL concurrency limit reached job_id=%s provider=%s",
            get_current_job_id(),
            provider,
        )
        raise PortalConcurrencyError(LOCAL_LIMIT_MESSAGE)

    try:
        yield
    finally:
        semaphore.release()
