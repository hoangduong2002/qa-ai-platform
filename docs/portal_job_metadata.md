# Portal job metadata storage

Portal job status uses the job-specific runtime file:

```text
<project-root>/runtime/portal_jobs/{job_id}_metadata.json
```

The writer serializes the complete JSON document in memory, writes and flushes
a same-directory temporary file, calls `fsync`, then installs it with
`os.replace`. In-process reads and writes use a shared `threading.RLock`.
Readers retry invalid JSON three times in total with 25 ms and 50 ms delays.

Copies named `latest_job_metadata.json` under a ticket's staging or analysis
directory are diagnostic snapshots only. They are not the source of truth for
`GET /portal/jobs/{job_id}/status`.

The lock prevents competing reads and writes inside one application process.
It does not coordinate separate Uvicorn workers or application instances.
Atomic replacement still prevents a reader in another process from observing
partially written JSON, but independent processes can overwrite newer state
with older state. If multi-process job writers are introduced, use an
inter-process file lock or a transactional shared store. The current documented
development command starts one Uvicorn worker.
