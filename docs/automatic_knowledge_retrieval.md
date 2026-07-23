# Automatic Knowledge retrieval for Requirement Analysis

Jira-sourced Requirements now resolve a Knowledge Base from the normalized Jira
Project Key and retrieve published references automatically before Requirement
Analysis. Opening **Review Knowledge References** is not required to activate
retrieval.

## Workflow

The Portal background job performs:

```text
fetch Jira -> create/sanitize Requirement -> resolve Jira Project Key mapping
-> bounded Knowledge search -> persist snapshot -> inject selected references
-> run Requirement Analysis -> persist the linked Analysis run
```

The normal **Analyze** and **Generate Summary** actions use the same preparation
path. Manual Requirements receive the explicit `no_project_key` status and
continue without automatically choosing a Knowledge Base.

Jira remains authoritative. Business/domain references are classified as
authoritative by a documented compatibility heuristic; API/integration and
existing-test references are supporting; defects are historical; guidelines do
not override product behavior. The Analysis prompt requires `[REF-xxx]`
citations for Knowledge-derived claims and explicit reporting of conflicts.

## Configuration

Existing flags remain authoritative:

```env
KNOWLEDGE_BASE_ENABLED=true
KNOWLEDGE_RETRIEVAL_ENABLED=true
KNOWLEDGE_RETRIEVAL_SHADOW_MODE=false
```

Automatic retrieval is bounded by:

```env
KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERIES=5
KNOWLEDGE_AUTO_RETRIEVAL_TOP_K=5
KNOWLEDGE_AUTO_RETRIEVAL_MAX_RESULTS=30
KNOWLEDGE_AUTO_RETRIEVAL_MAX_SELECTED=10
KNOWLEDGE_AUTO_RETRIEVAL_MAX_CONTEXT_CHARS=12000
KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERY_CHARS=500
KNOWLEDGE_AUTO_RETRIEVAL_MIN_SCORE=
```

The score threshold is intentionally empty by default because SQLite FTS/BM25
scores are relative and may be negative. Results are ordered by descending
score, then stable source identity. Search uses active indexed chunks only,
deduplicates repeated query hits, and applies both reference-count and character
budgets.

## Statuses and fallback

Every Analysis attempt writes one snapshot with one of:

- `disabled`
- `retrieval_disabled`
- `no_project_key`
- `no_mapping`
- `kb_not_ready`
- `no_matches`
- `completed`
- `completed_with_warnings`
- `failed`

The Requirement and Analysis path remain usable without Knowledge for every
fallback status. Internal search failures are logged, while saved/UI messages
contain no internal path or exception detail. Snapshot persistence failure
stops Analysis rather than claiming nonexistent traceability.

## Artifacts

```text
requirements/{ticket}/knowledge/latest_snapshot.json
requirements/{ticket}/knowledge/snapshots/{snapshot_id}.json
requirements/{ticket}/analysis/latest_analysis_run.json
requirements/{ticket}/analysis/runs/{analysis_run_id}.json
```

Snapshots record the Jira Project Key, actual `kb_id`, queries, scores,
collection/document/version/chunk identities, hashes, safe excerpts, selection,
prompt inclusion, authority role, and the Analysis run ID. Previous snapshots
and versioned Analysis runs are not overwritten.

## Optional review and rerun

The existing review screen now displays the automatic snapshot, queries, scores,
authority, selected state, and exact candidate excerpts. Reviewers can accept or
reject candidates using the existing authorization policy, then select
**Re-run Analysis with Reviewed Selection**. This creates a new immutable
snapshot with `selection_mode: reviewed` and `based_on_snapshot_id`; the
original automatic snapshot remains unchanged.

Read-only snapshot/reference data is available at:

```http
GET /portal/requirements/{ticket_id}/knowledge-references
```

This implementation does not change Knowledge Package import, Jira
authentication, Knowledge Base mapping CRUD, document approval, or perform
independent retrieval in Scenario/Test Case stages. Those stages continue to
consume the current Analysis artifacts.
