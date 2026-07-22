# Layered environment configuration

The application loads configuration once through `app.config.env_loader` in
this order:

```text
.env < .env.ai < .env.qa < .env.secrets < process environment
```

Later files override earlier files, including with an explicit empty value.
An existing process variable always wins. Every file is optional so rule-based
and `NO_LLM` commands can run without provider credentials.

## Variable ownership

Before this migration, non-secret settings and blank credential placeholders
were mixed in `.env`; real credentials were already supported in
`.env.secrets`. The target ownership table is:

| Variable name | Previous location | Target | Secret | Default/example | Main consumers |
| --- | --- | --- | --- | --- | --- |
| `APP_TIMEZONE`, `LOG_LEVEL` | `.env` | `.env` | No | `.env.example` | chat/runtime logging |
| `JIRA_SERVER_URL`, `JIRA_AUTH_MODE`, `JIRA_VERIFY_SSL`, `JIRA_INCLUDE_SUBTASKS` | `.env` | `.env` | No | `.env.example` | Jira requirement service |
| `FIGMA_ENABLE_EXTRACTION`, `FIGMA_EXTRACT_SCOPE`, `FIGMA_ALLOW_FIRST_PAGE_FALLBACK`, `FIGMA_MAX_*`, `FIGMA_MIN_*`, `FIGMA_PAGE_*`, `FIGMA_LAYER_*`, `FIGMA_IMAGE_EXPORT_BATCH_SIZE`, `FIGMA_EXPORT_SCALE`, `FIGMA_EXPORT_FORMAT`, `FIGMA_EXPORT_CONTAINER_LAYERS` | `.env` | `.env` | No | `.env.example` | Figma requirement service |
| `SANITIZE_REQUIREMENT`, `REDACT_*`, `REQUIREMENT_CHUNK_MAX_CHARS`, `REQUIREMENT_COMPACT_*` | `.env` | `.env` | No | `.env.example` | sanitizing/compaction |
| `IMPROVE_*`, `TESTCASE_*`, `MAX_STRUCTURE_REVIEW_ITERATIONS`, `SCENARIO_*`, `COVERAGE_REVIEW_PARALLEL_WORKERS`, `FINAL_REVIEW_PARALLEL_WORKERS`, `INCREMENTAL_MAJOR_CHANGE_THRESHOLD` | `.env` | `.env` | No | `.env.example` | generation workflow |
| `CHAT_*`, `KNOWLEDGE_SYSTEM_*` | `.env` | `.env` | No | `.env.example` | Web Portal |
| `TELEGRAM_AI_MODE`, `PORTAL_DEFAULT_AI_MODE`, `NON_PORTAL_AI_MODE`, `MAX_CLARIFICATIONS_PER_ROUND`, `MAX_CLARIFICATION_ROUNDS` | `.env` | `.env.ai` | No | `.env.ai.example` | shared LLM router |
| `DEEPSEEK_*` except `DEEPSEEK_API_KEY`, plus `ALLOW_DEEPSEEK_PRO`, `FORCE_DISABLE_DEEPSEEK` | `.env` | `.env.ai` | No | `.env.ai.example` | DeepSeek provider |
| `COPILOT_*` except `COPILOT_API_KEY`, plus `FORCE_DISABLE_COPILOT` | `.env` | `.env.ai` | No | `.env.ai.example` | Copilot provider |
| `LOCAL_*`, `FORCE_DISABLE_LOCAL_AI`, `MAX_CONCURRENT_*`, `LLM_*`, `AI_DRY_RUN`, `AI_USAGE_LOG_PATH` | `.env` | `.env.ai` | No | `.env.ai.example` | routing and limits |
| `KNOWLEDGE_BASE_*` except `KNOWLEDGE_BASE_MAINTAINER_TOKEN` | `.env`/defaults | `.env.qa` | No | `.env.qa.example` | Knowledge Base |
| `STRUCTURED_ANALYSIS_*`, `REQUIREMENT_QUALITY_*` | defaults | `.env.qa` | No | `.env.qa.example` | analysis quality |
| `KNOWLEDGE_RETRIEVAL_*`, `KNOWLEDGE_REFERENCE_*`, `KB_ANALYSIS_ENRICHMENT_MODE` | defaults | `.env.qa` | No | `.env.qa.example` | retrieval/review/enrichment |
| `COVERAGE_MODEL_MODE`, `TEST_CASE_GENERATOR_VERSION` | defaults | `.env.qa` | No | `.env.qa.example` | coverage and generator selection |
| `TEST_QUALITY_*`, `TRACEABILITY_GATE_ENABLED`, `EXPORT_QUALITY_*`, `EXPORT_GATE_*` | defaults | `.env.qa` | No | `.env.qa.example` | reviewer and export guard |
| `QA_FEEDBACK_REVIEWER_IDS`, `GOLDEN_DATASET_REVIEWER_IDS`, `*_VERSION` | defaults | `.env.qa` | No | `.env.qa.example` | feedback/evaluation metadata |
| `DEEPSEEK_API_KEY`, `COPILOT_API_KEY`, `TELEGRAM_BOT_TOKEN`, `FIGMA_ACCESS_TOKEN`, `JIRA_PAT`, `JIRA_API_TOKEN`, `JIRA_USERNAME`, `JIRA_PASSWORD`, `GITHUB_TOKEN`, `KNOWLEDGE_BASE_MAINTAINER_TOKEN` | `.env` or `.env.secrets` | `.env.secrets` | Yes | Empty in `.env.secrets.example` | provider/auth adapters |

The exact, machine-checked ownership registry is
`app/config/environment_schema.py`. `COVERAGE_MODEL_ENABLED` is deprecated;
use `COVERAGE_MODEL_MODE`.

Canonical AI modes are `TEST_LOCAL_ONLY`, `PRODUCTION_HYBRID_DEEPSEEK`,
`PRODUCTION_HYBRID_COPILOT`, `DEEPSEEK_ONLY`, `COPILOT_ONLY`, and `NO_LLM`.
Legacy aliases remain accepted for compatibility but are reported as
deprecated.

## Local setup and diagnostics

```powershell
Copy-Item .env.example .env
Copy-Item .env.ai.example .env.ai
Copy-Item .env.qa.example .env.qa
Copy-Item .env.secrets.example .env.secrets
python -m app.config.check
```

The diagnostic prints source files, active AI and QA modes, duplicate keys,
misplaced/unknown/deprecated variables, invalid enum values, and credential
status. It never prints credential values. A non-zero exit indicates invalid
ownership or values.

If two files define the same key, remove the lower-level copy instead of relying
on precedence. Restart long-running processes after changing any layer.

## CI and production

Do not copy local secret files into images. Inject secrets and deployment
overrides as process environment variables through the CI/CD secret store,
container orchestrator, or service manager. Process injection has the highest
priority. The checked-in `config/production-rollout.env` and
`config/rollback.env` are validation/deployment profiles; the application does
not auto-load them.

For the conservative QA rollout, start from `.env.qa.example`. Keep enrichment
manual, Generator V2 manually selectable, reviewer mode at `warn`, and the
export quality gate disabled until evaluation thresholds are met.

To restore the original workflow without reverting code, use these values in
`.env.qa` and restart all application processes:

```env
KNOWLEDGE_BASE_ENABLED=false
STRUCTURED_ANALYSIS_ENABLED=false
REQUIREMENT_QUALITY_GATE_ENABLED=false
KNOWLEDGE_RETRIEVAL_ENABLED=false
KB_ANALYSIS_ENRICHMENT_MODE=off
COVERAGE_MODEL_MODE=off
TEST_CASE_GENERATOR_VERSION=v1
TEST_QUALITY_REVIEW_ENABLED=false
TRACEABILITY_GATE_ENABLED=false
EXPORT_QUALITY_GATE_ENABLED=false
```

There is currently no Dockerfile or Compose file in this repository, so this
migration required no container change. If Compose is added, list the four
layers in the same order or, preferably for production, inject deployment
configuration and secrets as process environment values.
