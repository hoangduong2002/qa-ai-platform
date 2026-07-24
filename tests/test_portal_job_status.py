from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.env_loader import PROJECT_ROOT
from app.services import portal_job_service
from app.web import portal_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(portal_router.router)
    return TestClient(app)


def _job_context(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "ticket_id": "WEC-123",
        "action": "analyze_requirement",
        "status": "RUNNING",
        "current_step": "Sanitizing requirement",
    }


def test_existing_metadata_file_returns_http_200(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    job_id = "job_20260723114244_9d0bccca"
    path = portal_job_service.get_job_metadata_path(job_id)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_job_context(job_id)), encoding="utf-8")

    response = _client().get(f"/portal/jobs/{job_id}/status")

    assert response.status_code == 200
    assert response.json()["job_id"] == job_id
    assert response.json()["status"] == "RUNNING"
    assert response.json()["current_step"] == "Sanitizing requirement"


def test_unknown_job_returns_http_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        portal_job_service,
        "RUNTIME_PORTAL_JOBS_DIR",
        (tmp_path / "runtime" / "portal_jobs").resolve(),
    )

    response = _client().get("/portal/jobs/job_unknown/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


def test_corrupt_metadata_is_not_reported_as_job_not_found(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    job_id = "job_corrupt"
    path = portal_job_service.get_job_metadata_path(job_id)
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    response = _client().get(f"/portal/jobs/{job_id}/status")

    assert response.status_code == 503
    assert response.json()["detail"] == "Job status is temporarily unavailable."
    assert response.json()["detail"] != "Job not found."


def test_writer_and_reader_resolve_the_same_metadata_path(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    job_id = "job_writer_reader"

    portal_job_service._write_job_metadata(_job_context(job_id))

    expected_path = runtime_dir / f"{job_id}_metadata.json"
    assert portal_job_service.get_job_metadata_path(job_id) == expected_path
    assert expected_path.exists()
    assert portal_job_service.get_job_status(job_id)["job_id"] == job_id


def test_default_runtime_directory_is_absolute_and_project_rooted() -> None:
    assert portal_job_service.RUNTIME_PORTAL_JOBS_DIR.is_absolute()
    assert portal_job_service.RUNTIME_PORTAL_JOBS_DIR == (
        PROJECT_ROOT / "runtime" / "portal_jobs"
    ).resolve()


def test_atomic_write_replaces_complete_file_without_truncating_target(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "job_metadata.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    original_replace = portal_job_service.os.replace
    target_was_complete_before_replace: list[bool] = []
    fsync_calls: list[int] = []
    original_fsync = portal_job_service.os.fsync

    def inspecting_replace(source, destination):
        target_was_complete_before_replace.append(
            target.read_text(encoding="utf-8") == '{"version": 1}'
        )
        original_replace(source, destination)

    def recording_fsync(file_descriptor):
        fsync_calls.append(file_descriptor)
        original_fsync(file_descriptor)

    monkeypatch.setattr(portal_job_service.os, "replace", inspecting_replace)
    monkeypatch.setattr(portal_job_service.os, "fsync", recording_fsync)
    portal_job_service._write_json_atomic(target, {"version": 2})

    assert target_was_complete_before_replace == [True]
    assert len(fsync_calls) == 1
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_cleans_temporary_file_after_replace_failure(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "job_metadata.json"
    target.write_text('{"version": 1}', encoding="utf-8")

    def failing_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(portal_job_service.os, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        portal_job_service._write_json_atomic(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_empty_metadata_is_retried_then_rejected(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    retry_delays: list[float] = []
    monkeypatch.setattr(
        portal_job_service.time,
        "sleep",
        lambda delay: retry_delays.append(delay),
    )
    path = portal_job_service.get_job_metadata_path("job_empty")
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    with pytest.raises(portal_job_service.PortalJobMetadataInvalidError):
        portal_job_service.get_job_status("job_empty")
    assert retry_delays == [0.025, 0.05]


def test_temporarily_invalid_metadata_becomes_readable_on_retry(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    monkeypatch.setattr(portal_job_service.time, "sleep", lambda _delay: None)
    job_id = "job_retry"
    path = portal_job_service.get_job_metadata_path(job_id)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text
    attempts = 0

    def transient_read_text(self, *args, **kwargs):
        nonlocal attempts
        if self == path:
            attempts += 1
            if attempts == 1:
                return ""
            return json.dumps(_job_context(job_id))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read_text)

    metadata = portal_job_service.get_job_status(job_id)

    assert attempts == 2
    assert metadata["job_id"] == job_id


def test_permission_error_is_not_converted_to_not_found(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    job_id = "job_permission"
    path = portal_job_service.get_job_metadata_path(job_id)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def permission_error(self, *args, **kwargs):
        if self == path:
            raise PermissionError("denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", permission_error)
    with pytest.raises(PermissionError, match="denied"):
        portal_job_service.get_job_status(job_id)


def test_create_job_writes_complete_metadata_before_return(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)

    job_id = portal_job_service.create_job(
        ticket_id="WEC-123",
        action="create_requirement_from_jira",
        ai_mode_context=None,
    )

    path = portal_job_service.get_job_metadata_path(job_id)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "PENDING"
    assert portal_job_service.get_job_status(job_id)["current_step"] == "Queued"
    staging_dir = tmp_path / "requirements" / "_jobs" / "WEC-123"
    job_archive = staging_dir / f"{job_id}_metadata.json"
    latest_snapshot = staging_dir / "latest_job_metadata.json"
    assert json.loads(job_archive.read_text(encoding="utf-8"))["job_id"] == job_id
    assert json.loads(latest_snapshot.read_text(encoding="utf-8"))["job_id"] == job_id
    assert path.stat().st_size > 0
    assert job_archive.stat().st_size > 0
    assert latest_snapshot.stat().st_size > 0
    assert not list(runtime_dir.glob("*.tmp"))
    assert not list(runtime_dir.glob(".*.tmp"))


def test_concurrent_polling_and_progress_updates_never_read_partial_json(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    job_id = "job_concurrent"
    context = _job_context(job_id)
    portal_job_service._update_job_metadata(context)
    errors: list[Exception] = []
    observed_statuses: list[str] = []

    def writer(offset: int) -> None:
        try:
            for index in range(20):
                portal_job_service._update_job_metadata(
                    context,
                    {
                        "current_step": f"writer-{offset}-{index}",
                        "progress_percent": offset + index,
                    },
                )
        except Exception as error:
            errors.append(error)

    def reader() -> None:
        try:
            for _ in range(60):
                observed_statuses.append(
                    portal_job_service.get_job_status(job_id)["status"]
                )
        except Exception as error:
            errors.append(error)

    threads = [
        threading.Thread(target=writer, args=(0,)),
        threading.Thread(target=writer, args=(40,)),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert observed_statuses
    assert set(observed_statuses) == {"RUNNING"}
    assert portal_job_service.get_job_status(job_id)["current_step"].startswith(
        "writer-"
    )


def test_http_route_retries_transient_invalid_metadata(tmp_path, monkeypatch) -> None:
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    monkeypatch.setattr(portal_job_service.time, "sleep", lambda _delay: None)
    job_id = "job_http_retry"
    path = portal_job_service.get_job_metadata_path(job_id)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text
    attempts = 0

    def transient_read_text(self, *args, **kwargs):
        nonlocal attempts
        if self == path:
            attempts += 1
            if attempts == 1:
                return "{"
            return json.dumps(_job_context(job_id))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read_text)
    response = _client().get(f"/portal/jobs/{job_id}/status")

    assert response.status_code == 200
    assert attempts == 2
    assert response.json()["job_id"] == job_id


def test_completion_and_failure_metadata_remain_readable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)

    asyncio.run(
        portal_job_service.run_portal_ticket_job(
            ticket_id="WEC-OK",
            action="analyze_requirement",
            ai_mode_context=None,
            job_callable=lambda: "done",
            job_id="job_success",
        )
    )
    success = portal_job_service.get_job_status("job_success")
    assert success["status"] == "SUCCEEDED"
    assert success["ended_at"]

    def fail():
        raise RuntimeError("expected failure")

    with pytest.raises(RuntimeError, match="expected failure"):
        asyncio.run(
            portal_job_service.run_portal_ticket_job(
                ticket_id="WEC-FAIL",
                action="analyze_requirement",
                ai_mode_context=None,
                job_callable=fail,
                job_id="job_failure",
            )
        )
    failure = portal_job_service.get_job_status("job_failure")
    assert failure["status"] == "FAILED"
    assert failure["ended_at"]


def test_create_requirement_from_jira_still_returns_202_with_pollable_job(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime_dir = (tmp_path / "runtime" / "portal_jobs").resolve()
    monkeypatch.setattr(portal_job_service, "RUNTIME_PORTAL_JOBS_DIR", runtime_dir)
    monkeypatch.setattr(portal_router, "_dispatch_portal_job", lambda **_kwargs: None)

    response = _client().post(
        "/portal/requirements/from-jira",
        data={"issue_key": "WEC-123", "load_subtasks": "false", "load_figma": "false"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    status_response = _client().get(f"/portal/jobs/{job_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "PENDING"
    assert status_response.json()["job_id"] == job_id
