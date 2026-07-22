# QA AI Platform

AI-powered Requirement Analysis and Test Case Generation Platform for QA teams.

QA AI Platform helps transform raw requirements from text, Jira, files, and design artifacts into structured requirement analysis, clarification questions, test design structure, scenarios, test cases, coverage review, and Excel reports.

---

## 1. Quick Start

```powershell
git clone https://github.com/hoangduong2002/qa-ai-platform.git
cd qa-ai-platform

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
copy .env.example .env
copy .env.ai.example .env.ai
copy .env.qa.example .env.qa
copy .env.secrets.example .env.secrets
```

Update the four local files, run `python -m app.config.check`, then start the
Web Portal:

```powershell
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

```text
http://localhost:8000/portal
```

Run Telegram Bot:

```powershell
python -m bot.telegram_bot
```

---

## 2. Installation

### 2.1 Clone repository

```powershell
git clone https://github.com/hoangduong2002/qa-ai-platform.git
cd qa-ai-platform
```

### 2.2 Create virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 2.3 Install dependencies

```powershell
pip install -r requirements.txt
```

For development dependencies:

```powershell
pip install -r requirements-dev.txt
```

---

## 3. Environment Setup

Create the four local layers from their templates:

```powershell
copy .env.example .env
copy .env.ai.example .env.ai
copy .env.qa.example .env.qa
copy .env.secrets.example .env.secrets
```

The loader applies this deterministic precedence (rightmost wins):

```text
.env < .env.ai < .env.qa < .env.secrets < process environment
```

All four files are optional. `.env` owns base runtime settings, `.env.ai` owns
provider/routing settings, `.env.qa` owns QA workflow feature flags, and
`.env.secrets` owns credentials. Do not commit local layers; commit only their
matching `*.example` files.

If they were already tracked:

```powershell
git rm --cached .env
git rm --cached .env.ai
git rm --cached .env.qa
git rm --cached .env.secrets
```

See `docs/environment_configuration.md` for ownership, deployment injection,
validation, and migration details.

---

## 4. Required Environment Values

At minimum, configure one AI provider.

### 4.1 DeepSeek

Use this when running `PRODUCTION_HYBRID_DEEPSEEK` or `DEEPSEEK_ONLY`.

`.env.ai`:

```env
TELEGRAM_AI_MODE=PRODUCTION_HYBRID_DEEPSEEK
PORTAL_DEFAULT_AI_MODE=NO_LLM

DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=120
ALLOW_DEEPSEEK_PRO=false
FORCE_DISABLE_DEEPSEEK=false
```

`.env.secrets`:

```env
DEEPSEEK_API_KEY=
```

### 4.2 Copilot

Use this when running `PRODUCTION_HYBRID_COPILOT` or `COPILOT_ONLY`.

Place these non-secret settings in `.env.ai`:

```env
COPILOT_BASE_URL=http://localhost:3100/v1/chat/completions
COPILOT_MODEL=claude-sonnet-4.6
COPILOT_TIMEOUT=120
FORCE_DISABLE_COPILOT=false
MAX_CONCURRENT_COPILOT_CALLS=2
```

Store `COPILOT_API_KEY` in `.env.secrets`.

Smoke-test the Copilot-compatible endpoint:

```powershell
$body = @{
  model = "claude-sonnet-4.6"
  messages = @(@{ role = "user"; content = "Say hello in one sentence." })
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://localhost:3100/v1/chat/completions" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### 4.3 Local AI / Ollama

Use this when running `TEST_LOCAL_ONLY` or when a production hybrid mode needs local compact/vision.

```env
LOCAL_AI_PROVIDER=OLLAMA
LOCAL_BASE_URL=http://localhost:11434

LOCAL_TEXT_MODEL=qwen2.5:14b
LOCAL_COMPACT_MODEL=
LOCAL_VISION_MODEL=qwen2.5vl:7b

LOCAL_TEXT_TIMEOUT=180
LOCAL_COMPACT_TIMEOUT=180
LOCAL_VISION_TIMEOUT=240

FORCE_DISABLE_LOCAL_AI=false
```

For Ollama running on another LAN machine:

```env
LOCAL_BASE_URL=http://<LAN_IP>:11434
```

Check connectivity:

```powershell
Invoke-RestMethod http://<LAN_IP>:11434/api/tags
```

### 4.4 Web Portal LLM Health Check

The Web Portal header includes a `Test All LLMs` button. It tests every configured provider independently:

* `DEEPSEEK`
* `COPILOT`
* `LOCAL_TEXT`
* `LOCAL_VISION`

For text providers, the check sends only this short prompt: `Reply with exactly: OK`.
For `LOCAL_VISION`, the check only verifies that `LOCAL_VISION_MODEL` is available in Ollama by calling `/api/show`; it does not send an image and does not test real image understanding.
The check does not require a requirement, does not create portal job files, does not save requirement artifacts, and does not call Jira or Figma.

Status meanings:

* `OK`: provider responded with non-empty content.
* `FAILED`: provider is configured and enabled, but the request failed.
* `SKIPPED`: provider is not configured, such as a missing API key, base URL, or model.
* `DISABLED`: provider is disabled by a `FORCE_DISABLE_*` setting.

```env
LLM_HEALTH_CHECK_TIMEOUT=30
```

### 4.5 Web Portal AI Chat

Open the chat page from the portal header or directly:

```text
http://localhost:8000/portal/chat
```

AI Chat supports multi-turn sessions, assistant Markdown rendering, copying assistant responses, and file context extraction for:

```text
.txt, .md, .json, .csv, .xlsx, .docx, .pdf
```

PDF support is text-based only. Phase 1 does not perform OCR, image vision, streaming responses, voice input, image generation, internet browsing, or Jira/Figma actions from chat.

Chat LLM calls use the normal shared LLM router with `source_channel=web_chat` and `task_type=chat`. Select one of the supported AI modes in the portal header or chat composer:

```text
PRODUCTION_HYBRID_DEEPSEEK
PRODUCTION_HYBRID_COPILOT
DEEPSEEK_ONLY
COPILOT_ONLY
TEST_LOCAL_ONLY
NO_LLM
```

Configuration:

```env
CHAT_MAX_UPLOAD_MB=10
CHAT_MAX_EXTRACTED_CHARS=60000
CHAT_HISTORY_MAX_MESSAGES=10
CHAT_SESSIONS_DIR=runtime/chat_sessions
CHAT_UNLOCK_TOKEN_TTL_HOURS=8
```

Recent chats can be deleted from the AI Chat sidebar. Delete is a soft delete:
the session folder remains on disk, but `session.json` is marked with
`deleted=true` and the chat no longer appears in Recent Chats.

New chats can optionally be password protected. Passwords are never stored in
plain text; the file-based chat store keeps only a PBKDF2 password hash and
salt in `session.json`. Protected chats must be unlocked before messages are
returned. Unlock tokens expire after `CHAT_UNLOCK_TOKEN_TTL_HOURS`.

Browser storage behavior:

```text
localStorage["qa_ai_platform_browser_id"]              = browser identifier
localStorage["qa_ai_platform_last_chat_session_id"]    = last opened chat
localStorage["qa_ai_platform_recent_chats"]            = recent metadata only
sessionStorage["chat_unlock_token_<session_id>"]       = temporary unlock token
```

Passwords are not stored in browser storage. Protected chat messages are not
cached in browser storage. This file-based password protection is suitable for
shared portal usage, but it is not a full enterprise authentication system. For
strong multi-user isolation, add real login and authorization later.

AI Chat includes a lightweight reliability layer before LLM routing:

* Simple rule-based task classification runs locally and does not call an LLM.
* Deterministic date/time questions are answered by an internal datetime tool
  using `APP_TIMEZONE` when configured.
* Simple arithmetic is answered by a safe calculator parser, not Python `eval`.
* Language, QA analysis, file summaries, code help, and broader reasoning still
  use the configured LLM through the shared router.
* The chat model has no internet browsing. If browsing/current-source lookup is
  implemented later, it should be exposed as an explicit tool result; until then
  live online/source-checking claims are treated as unverified.

### 4.6 Jira

Required when importing or syncing Jira requirements.

`.env`:

```env
JIRA_SERVER_URL=https://your-jira-server
JIRA_AUTH_MODE=PAT
JIRA_VERIFY_SSL=true
JIRA_INCLUDE_SUBTASKS=true
```

In the Web Portal, use **Load Requirement from Jira** to import either one Jira
ticket or a main ticket with supporting requirement tickets:

```text
EVNWCL-5175
EVNWCL-5175, EVNWCL-5176, EVNWCL-5177
```

Ticket IDs are comma-separated. The first ticket is the main requirement and
determines the requirement folder (for example, `requirements/EVNWCL-5175/`).
All following tickets are loaded into that requirement as supporting context.
Duplicates and empty comma-separated entries are ignored, and ticket IDs are
normalized to uppercase.

The **Load sub-tasks** checkbox controls whether sub-tasks are fetched for the
main and supporting tickets. Its initial value follows `JIRA_INCLUDE_SUBTASKS`.
The **Load Figma** checkbox controls Jira Figma-link detection, export, and
vision analysis. Its initial value follows `FIGMA_ENABLE_EXTRACTION`; when it is
off, requirement analysis uses Jira text and attachments without calling Figma.

`.env.secrets`:

```env
JIRA_PAT=
```

### 4.7 Figma

Required only when Figma extraction is enabled.

`.env`:

```env
FIGMA_ENABLE_EXTRACTION=true
FIGMA_EXTRACT_SCOPE=linked_page
FIGMA_ALLOW_FIRST_PAGE_FALLBACK=false
```

`.env.secrets`:

```env
FIGMA_ACCESS_TOKEN=
```

### 4.8 Knowledge System

The Web Portal exposes `/portal/knowledge` as a directory of project-specific
knowledge assistants and RAG systems. Enable it and select the project config
file in `.env`:

```env
KNOWLEDGE_SYSTEM_ENABLED=true
KNOWLEDGE_SYSTEM_LINK_TARGET=_blank
KNOWLEDGE_SYSTEM_CONFIG_PATH=config/knowledge_projects.json
KNOWLEDGE_SYSTEM_PROJECTS_JSON=
KNOWLEDGE_SYSTEM_ALLOW_HTTP=false
```

Add assistants to `config/knowledge_projects.json`:

```json
[
  {
    "key": "weclever",
    "name": "Weclever Business Knowledge Assistant",
    "description": "RAG assistant for Weclever business knowledge and project information.",
    "url": "https://chatgpt.com/g/g-6a54488069d081919d0131b19972abca-weclever-business-knowledge-assistant",
    "enabled": true,
    "tags": ["Business", "Requirement", "RAG"]
  }
]
```

If the config file is missing or not configured, the service can load the same
JSON array from `KNOWLEDGE_SYSTEM_PROJECTS_JSON`. Disabled entries are omitted.
HTTPS is required by default. Set `KNOWLEDGE_SYSTEM_ALLOW_HTTP=true` only for a
trusted internal knowledge system that cannot use HTTPS.

The portal only opens configured external links. It does not embed ChatGPT,
scrape or automate its UI, or forward chat messages. Authentication and access
remain controlled by ChatGPT or the external knowledge system. Do not include
access tokens, credentials, or other secrets in assistant URLs.

### 4.9 Coverage Model Builder (Phase 7)

Phase 7 builds a deterministic structured coverage model between test-scope
generation and scenario generation:

```env
COVERAGE_MODEL_MODE=off
```

Allowed modes are `off`, `shadow`, and `enabled`. `off` preserves the legacy
scenario path without writing coverage artifacts. `shadow` writes
`requirements/<ticket>/test-design/coverage_model.json` and
`coverage_analysis.md` but does not alter scenario prompts. `enabled` adds a
concise coverage context to the existing scenario generator. The legacy
`COVERAGE_MODEL_ENABLED` setting remains supported for backward compatibility,
but new configuration should use `COVERAGE_MODEL_MODE`.

### 4.10 Test Case Generator V2 (Phase 8)

Phase 8 adds a source-grounded V2 generator behind a versioned rollout setting:

```env
TEST_CASE_GENERATOR_VERSION=v1
```

Supported values are `v1`, `v2-shadow`, `v2-manual`, and `v2`. Use
`v2-shadow` for the Phase 8 rollout. It runs V1 and V2 independently, keeps V1
as the production/UI/export result, and writes these comparison artifacts:

- `requirements/<ticket>/test-design/testcases_v1.json`
- `requirements/<ticket>/test-design/testcases_v2.json`
- `requirements/<ticket>/test-design/generator_comparison.json`

V2 only receives the Jira source, structured or explicitly approved enriched
analysis, ACCEPTED Knowledge Base references, unresolved conflicts, the Phase 7
coverage model, approved scenarios, and scope/output constraints. Unsupported
expected behavior is rejected unless it is explicitly recorded as an assumption
or unresolved question. Set the flag back to `v1` for immediate rollback.

### 4.11 Independent Test Quality Review (Phase 9)

Phase 9 adds deterministic validation followed by an independent reviewer and
a bounded correction cycle:

```text
Generator V2 -> Reviewer -> Corrector -> Reviewer
```

There are at most two review attempts and one correction attempt. Enable the
Phase 9 warning rollout with:

```env
TEST_QUALITY_REVIEW_ENABLED=true
TEST_QUALITY_REVIEW_MODE=warn
```

Modes are `off`, `warn`, and `block_export`. Warning mode records blockers but
does not change the current export. `block_export` rejects export while the
final report status is `NEEDS_QA_REVIEW`.

The reviewer and corrector have separate task types and prompts. They may also
use provider/model profiles independent from generation:

```env
TEST_QUALITY_REVIEW_AI_MODE=
TEST_QUALITY_REVIEW_MODEL=
TEST_QUALITY_CORRECTOR_AI_MODE=
TEST_QUALITY_CORRECTOR_MODEL=
```

Phase 9 writes `test_quality_report.json`, `correction_history.json`, and
`testcases_v2_reviewed.json` under `requirements/<ticket>/test-design/`.

### 4.12 Traceability Gate and Export Protection (Phase 10)

Phase 10 builds `requirements/<ticket>/traceability.json`, connecting Jira
sections, acceptance criteria, business rules, approved Knowledge Base
references, coverage conditions, scenarios, test cases, and expected results.
Edges are emitted only when both endpoint objects exist; stale references are
reported as validation issues.

Progressive rollout starts with report-only traceability and a warning guard:

```env
TRACEABILITY_GATE_ENABLED=true
EXPORT_QUALITY_GATE_ENABLED=true
EXPORT_QUALITY_GATE_MODE=warn
```

Change `EXPORT_QUALITY_GATE_MODE` to `block` to enforce configured rules. Each
rule can be controlled independently with the `EXPORT_GATE_BLOCK_*` settings in
`.env.qa.example`. The guard wraps the existing full and incremental XLSX
exporters; it does not duplicate workbook generation.

Authorized QA Lead overrides require a named identity, reason, scope, timestamp,
and all affected blocker IDs:

```env
EXPORT_GATE_QA_LEAD_IDS=qa.lead@example.com
```

Overrides are appended to
`requirements/<ticket>/audit/export_overrides.jsonl`. Setting both Phase 10
feature flags to `false` restores the previous export path.

### 4.13 QA Feedback and Continuous Evaluation (Phase 11)

The testcase page can record authorized accept, edit, reject, quality, coverage,
and reference decisions. Events are appended under
`requirements/<ticket>/feedback/testcase_feedback.jsonl`; testcase bodies are
represented by canonical SHA-256 hashes, and aggregate reports contain no Jira
or testcase body text.

```env
QA_FEEDBACK_REVIEWER_IDS=qa.user@example.com
GOLDEN_DATASET_REVIEWER_IDS=qa.lead@example.com
```

Golden dataset changes are explicit reviewer actions. They anonymize the ticket,
create an immutable version under `evaluation/datasets/<dataset>/versions/`, and
record the approval, reason, versions, and hashes in `manifest.json`. Existing
expectations cannot be replaced without an expectation-change reason. No
production ticket is added automatically and no model training occurs.

Run deterministic, credential-free regression evaluation with:

```powershell
python -m evaluation.run --dataset weclever_golden --deterministic --compare-baseline evaluation/baselines/weclever_golden.json --thresholds evaluation/critical_thresholds.json --fail-on-regression
```

See `evaluation/README.md` for prompt/model/retrieval/ranking comparisons,
per-domain reports, privacy-safe trend reports, and the controlled golden CLI.

### 4.14 Telegram

Required only when running Telegram Bot.

`.env.secrets`:

```env
TELEGRAM_BOT_TOKEN=
```

### 4.15 Production rollout and rollback

Use `config/production-rollout.env` for the conservative Phase 0–11 rollout and
`config/rollback.env` for code-free restoration of the original analysis, V1
generator, reviewer-off mode, and original exporter. Validate either profile
with `python -m app.services.rollout_readiness`.

The complete setup, FTS5, backup, restore, index rebuild, interrupted-publish,
rollout, rollback and troubleshooting procedures are in
`docs/production_rollout.md`.

---

## 5. Run Commands

### 5.1 Run Web Portal

```powershell
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

```text
http://localhost:8000/portal
```

If accessing from another machine in LAN:

```text
http://<HOST_IP>:8000/portal
```

### 5.2 Run Telegram Bot

```powershell
python -m bot.telegram_bot
```

Common commands:

```text
/generate_text
```

Create requirement from text.

```text
/generate <ticket_id>
```

Generate test cases from an existing requirement.

```text
/generate_jira <issue_key>
```

Create requirement from Jira, analyze, clarify, then continue generation.

```text
/analyze <ticket_id>
```

Run requirement analysis, clarification generation, and requirement summary.

```text
/requirements
```

List requirements.

```text
/status <ticket_id>
```

Show requirement status.

```text
/add_text <ticket_id>
```

Add more requirement notes.

```text
/report
```

Show AI usage, token usage, processing time, and generated assets.

### 5.3 Run Tests

Run all tests:

```powershell
pytest
```

Run selected tests:

```powershell
pytest test_llm_router.py
pytest test_jira_delta_compare.py
pytest test_impact_mapping.py
pytest test_incremental_merge.py
pytest test_figma_export.py
```

### 5.4 Check Effective Environment

Use this when the app appears to read stale or unexpected layered values. The
report masks credentials and identifies duplicate, misplaced, unknown, and
deprecated keys.

```powershell
python -m app.config.check
```

### 5.5 Stop Existing Python Processes

Use this when old server/bot processes are still holding old environment values.

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

## 6. Project Goals

QA AI Platform is designed to help QA teams:

* Analyze product requirements.
* Identify missing or ambiguous information.
* Generate clarification questions.
* Create structured test design.
* Generate scenarios and test cases.
* Review coverage and improve generated test cases.
* Maintain traceability from requirement to scenario to test case.
* Export QA artifacts to Excel.
* Support Jira change synchronization and incremental regeneration.

High-level flow:

```text
Requirement
  ↓
Requirement Analysis
  ↓
Clarification Questions
  ↓
Requirement Summary
  ↓
Test Design Structure
  ↓
Scenario Generation
  ↓
Test Case Generation
  ↓
Coverage Review / Improvement
  ↓
Final Review
  ↓
Excel Export
```

---

## 7. Main Capabilities

### Requirement Intelligence

* Create requirements manually from Web Portal.
* Import requirements from Jira.
* Upload files and extract requirement context.
* Sanitize requirement content.
* Analyze requirement into structured information.
* Generate clarification questions.
* Save clarification answers.
* Generate requirement summary.
* Track requirement items.

### Test Design

* Generate test case structure.
* Self-review and improve structure.
* Approve test structure before generation.
* Generate test scope and scenarios.
* Review and improve scenarios.
* Approve scenario versions.
* Generate test cases from approved scenarios.
* Improve test cases from AI review or human review.
* Run final coverage review.

### Jira Change Management

* Detect whether a requirement was imported from Jira.
* Create initial Jira snapshot.
* Sync Jira changes.
* Compare old and new Jira snapshots.
* Generate change impact report.
* Build regeneration plan.
* Run incremental requirement analysis.
* Generate incremental scenarios.
* Generate incremental test cases.
* Export incremental Excel report.

### Figma / Design Support

* Detect Figma links from requirement content.
* Resolve linked Figma page/node.
* Extract sections and frames.
* Export frame images.
* Analyze images using Local Vision when AI mode allows it.
* Skip vision gracefully when Local Vision is unavailable.

### Export

* Requirement analysis Excel.
* Requirement summary Excel.
* Test structure Excel.
* Scenario Excel.
* Test case Excel.
* Incremental test case Excel.
* Coverage / traceability information.

### Playwright Automation Classification

Generated test cases include execution metadata:

* `execution_type`: `AUTOMATION`, `MANUAL`, or `HYBRID`.
* `automation_candidate`: true when the case is suitable for Playwright automation.
* `automation_tool`: defaults to `Playwright` for automation candidates.
* `automation_priority`: `High`, `Medium`, `Low`, or `Not Applicable`.
* `automation_reason`, `automation_blockers`, and `manual_reason` explain the classification.

`AUTOMATION` is used for reliable browser UI flows with deterministic assertions.
`MANUAL` is used for human judgment, subjective UX review, external confirmation,
physical device work, visual-only validation, unstable data, or manual approval.
`HYBRID` is used when Playwright can cover part of the flow but final verification
still requires manual review.

Test case Excel exports include:

* `All Test Cases`
* `Automation Candidates`
* `Manual Test Cases`
* `Automation Summary`

### Channels

* Web Portal.
* Telegram Bot.
* CLI/test scripts.

---

<!-- Continue the rest of README from the Architecture Overview section onward. -->

```
```
