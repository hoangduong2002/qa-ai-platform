# Phases 0–11 Production Rollout and Recovery Guide

## Architecture and rollback boundaries

The Jira source remains authoritative. The legacy analysis runs first and is
preserved at `requirements/<ticket>/analysis/requirement_analysis.json`.
Structured analysis, requirement quality, reviewed Knowledge Base references,
enrichment, the coverage model, Generator V2, the independent reviewer, and
traceability are additive stages around that path.

The initial production profile has these boundaries:

1. Legacy analysis is retained while structured analysis produces its versioned
   sidecar artifact.
2. Knowledge retrieval creates candidates only. A named reviewer must accept a
   reference before enrichment or generation can consume it.
3. Enrichment is manual and inactive until its per-ticket approval exists.
4. The coverage model runs in shadow mode and cannot change scenario prompts.
5. V1 and V2 both run in `v2-manual`; V1 remains selectable and exportable.
6. The independent reviewer warns and records corrections but does not block
   export.
7. Traceability reports are generated; the export quality gate remains off, so
   the unchanged exporter retains control.

`QAState` only adds optional keys for these stages. Existing required state and
the V1 testcase schema are unchanged.

## Dependencies and clean setup

Supported deployment prerequisites:

- Python 3.12 recommended.
- Packages pinned in `requirements.txt`; test tools in `requirements-dev.txt`.
- A Python SQLite build with FTS5.
- A persistent local or mounted filesystem for `KNOWLEDGE_BASE_ROOT` and
  `requirements/`.
- Provider credentials only for the AI modes enabled in the deployment.

Windows setup:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
Copy-Item .env.ai.example .env.ai
Copy-Item .env.qa.example .env.qa
Copy-Item .env.secrets.example .env.secrets
.\.venv\Scripts\python.exe -m app.config.check
.\.venv\Scripts\python.exe -m knowledge.maintenance fts5
.\.venv\Scripts\python.exe -m pytest -q tests
```

The FTS5 command must return `"fts5_supported": true`. The HTTP equivalent,
after enabling the Knowledge Base, is `GET /api/knowledge/health`.

## Data directories

- `KNOWLEDGE_BASE_ROOT` (default `knowledge_bases/`): source documents,
  immutable published chunks, metadata, audit JSONL, SQLite indexes and index
  manifests.
- `requirements/`: Jira sources, analysis, reviewed references, design
  artifacts, traceability, QA feedback and override audit.
- `evaluation/datasets/`: checked-in golden baselines and immutable dataset
  versions.
- `reports/evaluation/`: generated evaluation reports; retain with the release
  record.
- `runtime/`: AI usage and application runtime logs. Treat as operational data,
  not a backup of source artifacts.

Use absolute paths for persistent production storage. The application account
needs read/write access; no directory should be web-served directly.

## Required initial configuration

Use `config/production-rollout.env` as the template. Resolve every placeholder
from the deployment secret store or identity configuration. Validate it before
deployment:

```powershell
.\.venv\Scripts\python.exe -m app.services.rollout_readiness --env-file config/production-rollout.env --profile conservative --evaluation-report reports/evaluation/release/evaluation_report.json --ticket <CANARY-TICKET> --output reports/rollout_readiness.json
```

The checked-in template intentionally fails authorization readiness until its
placeholders are supplied. Do not put the maintainer token in Git.

| Control | Initial value | Effect |
| --- | --- | --- |
| `KNOWLEDGE_BASE_ENABLED` | `true` | Enables Knowledge APIs and UI. |
| `STRUCTURED_ANALYSIS_ENABLED` | `true` | Produces structured analysis alongside legacy analysis. |
| `STRUCTURED_ANALYSIS_SHADOW_MODE` | `false` | Marks structured output active for downstream reviewed stages. |
| `REQUIREMENT_QUALITY_GATE_ENABLED` | `true` | Runs deterministic quality review. |
| `REQUIREMENT_QUALITY_GATE_MODE` | `warn` | Records issues without stopping the workflow. |
| `KNOWLEDGE_RETRIEVAL_ENABLED` | `true` | Allows new retrieval requests. |
| `KNOWLEDGE_RETRIEVAL_SHADOW_MODE` | `false` | Records normal review candidates; accepted references still require review. |
| `KNOWLEDGE_REFERENCE_REVIEW_REQUIRED` | `true` | Enforces the reviewer allowlist. |
| `KB_ANALYSIS_ENRICHMENT_MODE` | `manual` | Requires explicit per-ticket enrichment approval. |
| `COVERAGE_MODEL_MODE` | `shadow` | Produces coverage artifacts without changing scenarios. Legacy `COVERAGE_MODEL_ENABLED=shadow` is accepted. |
| `TEST_CASE_GENERATOR_VERSION` | `v2-manual` | Runs both generators; selection remains manual and defaults to V1. |
| `TEST_QUALITY_REVIEW_ENABLED` | `true` | Runs the independent reviewer. |
| `TEST_QUALITY_REVIEW_MODE` | `warn` | Never blocks current export. |
| `TRACEABILITY_GATE_ENABLED` | `true` | Generates and validates traceability reports. |
| `EXPORT_QUALITY_GATE_ENABLED` | `false` | Preserves original export behavior. |

Do not use `KB_ANALYSIS_ENRICHMENT_MODE=automatic`,
`TEST_CASE_GENERATOR_VERSION=v2`, or enable blocking export in this rollout.

## Health, evaluation and rollout checklist

Before canary traffic:

- [ ] Back up `KNOWLEDGE_BASE_ROOT`, `requirements/`, golden datasets and the
  release evaluation report.
- [ ] Confirm FTS5 and run `python -m knowledge.maintenance health --kb-id <KB>`
  for every configured Knowledge Base.
- [ ] Confirm all documents are `INDEXED`, no document is `PUBLISHING`, and each
  KB has `search.db` plus `index_manifest.json`.
- [ ] Confirm maintainer, reference reviewer, QA feedback and golden reviewer
  identities are configured; keep override identities separate.
- [ ] Run the complete test suite and the deterministic golden evaluation.
- [ ] Confirm zero critical regressions against
  `evaluation/critical_thresholds.json`.
- [ ] Run a canary ticket and inspect V1/V2 comparison, reviewer report,
  correction history, traceability and the final XLSX export.
- [ ] Confirm V1 is selected by default until a named QA user selects V2.
- [ ] Confirm export warnings are visible and export is still permitted.
- [ ] Store `reports/rollout_readiness.json` with the deployment record.

Evaluation command:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run --dataset weclever_golden --deterministic --compare-baseline --thresholds evaluation/critical_thresholds.json --fail-on-regression --output-dir reports/evaluation/release
```

Do not enable automatic enrichment, V2-only output, or blocking export until the
critical checks remain within threshold across the agreed canary sample and QA
has accepted the observed edit/rejection rate. Evaluation establishes
regression association, not defect-leakage causation.

## Backup procedure

1. Stop new imports, publishes, reviews and generation jobs.
2. Wait for portal jobs to finish and ensure no KB document is `PUBLISHING`.
3. Stop application workers so JSONL and SQLite files are quiescent.
4. Create a timestamped backup directory on a separate protected volume.
5. Copy `KNOWLEDGE_BASE_ROOT`, `requirements/`, `evaluation/datasets/`, the
   deployment environment excluding plaintext secrets, and release reports.
6. Record checksums and test opening representative JSON/JSONL files.

Example after the service is stopped:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = "D:\qa-ai-backups\$stamp"
New-Item -ItemType Directory -Path $backup
Copy-Item -Recurse -LiteralPath "F:\AI\qa-ai-platform\knowledge_bases" -Destination "$backup\knowledge_bases"
Copy-Item -Recurse -LiteralPath "F:\AI\qa-ai-platform\requirements" -Destination "$backup\requirements"
Copy-Item -Recurse -LiteralPath "F:\AI\qa-ai-platform\evaluation\datasets" -Destination "$backup\evaluation_datasets"
Copy-Item -Recurse -LiteralPath "F:\AI\qa-ai-platform\reports\evaluation" -Destination "$backup\evaluation_reports"
```

## Restore procedure

1. Stop all application workers and verify the chosen backup timestamp.
2. Move current data directories to a timestamped quarantine location; do not
   delete them.
3. Restore Knowledge Base and requirement directories to the exact configured
   paths with the original permissions.
4. Start one maintenance process only.
5. Run FTS5 verification, interrupted-publish recovery, and index rebuild for
   every KB.
6. Run KB health, a known retrieval query, artifact JSON validation, and a V1
   export smoke test before starting normal workers.

SQLite indexes are derived data. If an index is absent or corrupt, restore the
published chunks and rebuild rather than treating `search.db` as authoritative.

## Index rebuild and interrupted publish recovery

```powershell
.\.venv\Scripts\python.exe -m knowledge.maintenance recover --kb-id <KB> --actor <operator-id>
.\.venv\Scripts\python.exe -m knowledge.maintenance reindex --kb-id <KB> --actor <operator-id>
.\.venv\Scripts\python.exe -m knowledge.maintenance health --kb-id <KB>
```

Recovery changes stale `PUBLISHING` documents to `FAILED` and audits the named
operator. Inspect the failure, then use the existing retry-publish operation.
A failed rebuild leaves the previously active index available; do not remove
`.bak` or temporary index files while a publish is running.

## Explicit rollback procedure

The rollback does not require a code deployment:

1. Stop admission of new jobs and let running jobs finish.
2. Apply `config/rollback.env` through deployment configuration.
3. Restart workers so all processes load the same flags.
4. Validate the profile:

```powershell
.\.venv\Scripts\python.exe -m app.services.rollout_readiness --env-file config/rollback.env --profile rollback
```

5. Run one existing ticket through legacy analysis and V1 generation.
6. Export each supported format and compare it with the pre-rollout smoke
   fixture.
7. Leave additive artifacts in place for audit; disabled stages ignore them.

The rollback profile independently restores original requirement analysis,
disables new KB retrieval, selects V1, disables the independent reviewer, and
disables both traceability and export guards. It does not delete Knowledge Base,
V2, reviewer or traceability artifacts.

## Troubleshooting

| Symptom | Check | Recovery |
| --- | --- | --- |
| FTS5 unavailable | `python -m knowledge.maintenance fts5` | Install an official Python build containing SQLite FTS5 before enabling retrieval. |
| Retrieval disabled | `KNOWLEDGE_RETRIEVAL_ENABLED` | Set true consistently on every worker and restart. |
| KB search empty | KB health, document status and manifest | Recover interrupted publishes, then reindex from published chunks. |
| Publish stuck | Documents with `PUBLISHING` | Run named-actor recovery, inspect audit, retry publish. |
| Structured artifact missing | structured flags and provider logs | Re-run analysis; legacy output remains available. |
| Enrichment not used | mode and `enrichment_approval.json` | Keep manual; obtain explicit QA approval. |
| Coverage not affecting scenarios | `COVERAGE_MODEL_MODE=shadow` | Expected during initial rollout. Inspect artifact only. |
| V2 not exported | generator selection | Expected default in `v2-manual`; select V2 explicitly only after QA review. |
| Reviewer blockers visible | reviewer mode | In `warn`, resolve or record QA feedback; export remains unchanged. |
| Export unexpectedly blocked | both export flags and mode | Apply rollback values and restart all workers. |
| Readiness output leaks a token | deployment wrapper | The built-in report redacts the maintainer token; never add provider keys to rollout files. |

## Intentionally deferred

- Automatic KB enrichment.
- V2-only production generation.
- Blocking quality/export gates and automatic QA overrides.
- Automatic ingestion of production tickets into the golden dataset.
- Model training or prompt mutation from feedback.
- Claims that measured quality changes cause lower escaped-defect rates.
- A large analytics platform; current UI summaries and versioned reports remain
  the supported surface.
