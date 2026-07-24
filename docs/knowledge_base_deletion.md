# Knowledge Base deletion

Knowledge Base deletion is an authorized hard-delete of current operational
data. It is available to users who have the existing Knowledge Base maintainer
token.

## What is removed

Deletion removes the Knowledge Base directory, including its metadata,
collections, uploaded documents, parsing previews, published chunks, search
indexes, index manifests, and KB-owned ingestion artifacts. Jira Project Keys
stored in that metadata are released immediately and may be assigned to another
Knowledge Base.

Deleting a Knowledge Base removes its current operational documents, indexes,
collections, and Jira Project Key mappings. Existing Requirement analyses and
stored Knowledge Snapshots are preserved.

Historical snapshots remain self-contained and can continue to show the
deleted Knowledge Base ID, name, and retrieved references. New Jira Requirement
workflows find no mapping for a released project key and continue using the
existing no-Knowledge-Base fallback.

## Safety controls

- API writes reuse `X-Maintainer-Token` and
  `KNOWLEDGE_BASE_MAINTAINER_TOKEN`.
- Portal writes require the same token in the confirmation form.
- The confirmation value must exactly equal the Knowledge Base ID. This is
  validated on the server as well as in the browser.
- A shared per-KB operation lock prevents deletion during ingestion, publish,
  reindexing, or another deletion. The API returns HTTP 409 when the lock is
  busy; active work is not cancelled.
- IDs and canonical paths are validated before recursive removal. The target
  must be a non-symlink directory inside the configured Knowledge Base root and
  cannot be the root itself.
- The KB directory is atomically renamed into the root's `_deleting` staging
  area before cleanup, making it unavailable to normal APIs and Jira mapping
  resolution.
- Existing KB audit events and the deletion outcome are retained under
  `_config/deletion_audit/<kb_id>/audit.jsonl`, outside the deleted directory.

The REST operations are:

- `GET /api/knowledge/bases/{kb_id}/deletion-impact`
- `DELETE /api/knowledge/bases/{kb_id}` with JSON
  `{"confirmation": "<exact-kb-id>"}`.

## Recovery and Windows limitations

Removal uses bounded retries for transient Windows `PermissionError` failures
and attempts to clear read-only attributes. If a file remains open (for
example, by antivirus software), deletion returns a safe HTTP 500 response and
records a failure audit event. The staged `_deleting` directory is intentionally
left for diagnosis; success is never reported for partial cleanup.

There is no recycle bin or automatic restore. Before retrying operational
cleanup, stop the process holding the file, inspect the deletion audit, and
verify that the staged path belongs to the expected KB. Historical Requirement
artifacts do not need recovery because deletion never targets `requirements/`.
