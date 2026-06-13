import asyncio
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)

RUNTIME_PORTAL_JOBS_DIR = Path("runtime") / "portal_jobs"

TICKET_BUSY_MESSAGE = "This ticket is already being processed."
JOB_LIMIT_MESSAGE = "The portal is currently processing the maximum number of jobs. Please try again shortly."
LLM_LIMIT_MESSAGE = "The portal is currently processing the maximum number of LLM calls. Please try again shortly."
OLLAMA_LIMIT_MESSAGE = "The local AI server is currently busy. Please try again shortly."

# Provider safety messages
NO_LLM_BLOCKED_MESSAGE = (
    "AI mode is NO_LLM. This action requires an LLM. "
    "Select TEST_LOCAL_ONLY or PRODUCTION_HYBRID."
)
TEST_LOCAL_ONLY_UNAVAILABLE_MESSAGE = (
    "AI mode is TEST_LOCAL_ONLY but the local AI provider is not available. "
    "Check that the local server is running and LOCAL_AI_ENABLED=true."
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
_generation_semaphore: threading.BoundedSemaphore | None = None
_generation_semaphore_size: int | None = None
_llm_semaphore: threading.BoundedSemaphore | None = None
_llm_semaphore_size: int | None = None
_ollama_semaphore: threading.BoundedSemaphore | None = None
_ollama_semaphore_size: int | None = None


class PortalJobBusyError(RuntimeError):
    pass


class PortalConcurrencyError(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default

    return max(value, 1)


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
    global _llm_semaphore, _llm_semaphore_size

    _llm_semaphore, _llm_semaphore_size = _get_semaphore(
        "MAX_PARALLEL_LLM_CALLS",
        3,
        _llm_semaphore,
        _llm_semaphore_size,
    )
    return _llm_semaphore


def _ollama_limit() -> threading.BoundedSemaphore:
    global _ollama_semaphore, _ollama_semaphore_size

    _ollama_semaphore, _ollama_semaphore_size = _get_semaphore(
        "MAX_PARALLEL_OLLAMA_CALLS",
        1,
        _ollama_semaphore,
        _ollama_semaphore_size,
    )
    return _ollama_semaphore


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


def _runtime_job_path(job_id: str) -> Path:
    return RUNTIME_PORTAL_JOBS_DIR / f"{job_id}.json"


def _read_job_metadata(job_id: str) -> dict[str, Any] | None:
    path = _runtime_job_path(job_id)

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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
    _write_job_metadata(context)
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

    if current_step is not None:
        context["current_step"] = current_step
        context["step_label"] = current_step

    if step_label is not None:
        context["step_label"] = step_label
        context["current_step"] = step_label

    if message is not None:
        context["message"] = message
        context["detail"] = message

    if detail is not None:
        context["detail"] = detail
        context["message"] = detail

    if progress_percent is not None:
        context["progress_percent"] = max(0, min(100, int(progress_percent)))

    _write_job_metadata(context)


def get_job_status(job_id: str) -> dict[str, Any] | None:
    return _read_job_metadata(job_id)


def _ticket_lock(ticket_id: str) -> threading.Lock:
    with _ticket_locks_guard:
        lock = _ticket_locks.get(ticket_id)

        if lock is None:
            lock = threading.Lock()
            _ticket_locks[ticket_id] = lock

        return lock


def _write_job_metadata(context: dict[str, Any]) -> None:
    ticket_id = str(context.get("ticket_id") or "").strip()

    if not ticket_id:
        return

    metadata = {
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

    payload = json.dumps(metadata, indent=2, ensure_ascii=False)
    action = str(context.get("action") or "")

    # For create_requirement_from_jira, write metadata to a staging location
    # so that the requirement folder is not created prematurely.
    # Premature folder creation causes requirement_exists() to return True
    # and the Jira loader gets skipped.
    runtime_path = _runtime_job_path(str(context.get("job_id") or ""))
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(payload, encoding="utf-8")

    if action == "create_requirement_from_jira":
        jobs_dir = Path("requirements") / "_jobs" / ticket_id
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{context.get('job_id')}_metadata.json").write_text(
            payload,
            encoding="utf-8",
        )
        (jobs_dir / "latest_job_metadata.json").write_text(
            payload,
            encoding="utf-8",
        )
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
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "latest_job_metadata.json").write_text(
            payload,
            encoding="utf-8",
        )
        (analysis_dir / f"{context.get('job_id')}_metadata.json").write_text(
            payload,
            encoding="utf-8",
        )


def _copy_job_metadata_to_requirement(context: dict[str, Any]) -> None:
    """Copy job metadata from staging path to the requirement's analysis folder.

    Only call after the requirement has been fully created.
    """
    ticket_id = str(context.get("ticket_id") or "").strip()
    if not ticket_id:
        return

    analysis_dir = Path("requirements") / ticket_id / "analysis"
    jobs_dir = Path("requirements") / "_jobs" / ticket_id

    if not jobs_dir.exists():
        return

    # Only copy if the requirement directory now exists (it should after a
    # successful create_requirement_from_jira).
    analysis_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
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

    payload = json.dumps(metadata, indent=2, ensure_ascii=False)
    (analysis_dir / "latest_job_metadata.json").write_text(
        payload,
        encoding="utf-8",
    )
    (analysis_dir / f"{context.get('job_id')}_metadata.json").write_text(
        payload,
        encoding="utf-8",
    )

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
    _write_job_metadata(context)

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

        context["status"] = "SUCCEEDED"
        context["current_step"] = "Complete"
        context["step_label"] = "Complete"
        context["message"] = "Job completed."
        context["detail"] = "Job completed."
        context["progress_percent"] = 100

        # After a successful create_requirement_from_jira, the requirement
        # folder should now be complete.  Copy job metadata into the
        # requirement's analysis/ directory so it is visible alongside the
        # sanitized requirement.
        if action == "create_requirement_from_jira":
            _copy_job_metadata_to_requirement(context)

        return result
    except Exception as error:
        context["status"] = "FAILED"
        context["error"] = str(error)
        context["current_step"] = "Failed"
        context["step_label"] = "Failed"
        context["message"] = str(error)
        context["detail"] = str(error)
        logger.exception(
            "Portal job failed job_id=%s ticket_id=%s action=%s",
            job_id,
            ticket_id,
            action,
        )
        raise
    finally:
        context["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        context["duration_ms"] = int((time.time() - started) * 1000)
        _write_job_metadata(context)
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
    semaphore = _llm_limit()

    if not semaphore.acquire(blocking=False):
        logger.warning(
            "LLM concurrency limit reached job_id=%s provider=%s",
            get_current_job_id(),
            provider,
        )
        raise PortalConcurrencyError(LLM_LIMIT_MESSAGE)

    try:
        yield
    finally:
        semaphore.release()


@contextmanager
def limit_ollama_call(provider: str = ""):
    semaphore = _ollama_limit()

    if not semaphore.acquire(blocking=False):
        logger.warning(
            "Ollama concurrency limit reached job_id=%s provider=%s",
            get_current_job_id(),
            provider,
        )
        raise PortalConcurrencyError(OLLAMA_LIMIT_MESSAGE)

    try:
        yield
    finally:
        semaphore.release()
