# QA AI Platform

AI-powered Requirement Analysis and Test Case Generation Platform for QA teams.

The platform helps transform raw requirements from text, Jira, files, and design artifacts into structured requirement analysis, clarification questions, test design structure, scenarios, test cases, coverage review, and Excel reports.

---

## 1. Project Goals

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

## 2. Main Capabilities

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

### Channels

* Web Portal.
* Telegram Bot.
* CLI/test scripts.

---

## 3. Architecture Overview

```text
                 ┌──────────────────┐
                 │   Web Portal     │
                 └────────┬─────────┘
                          │
                 ┌────────▼─────────┐
                 │   FastAPI API    │
                 └────────┬─────────┘
                          │
┌─────────────────────────▼─────────────────────────┐
│                 Application Services              │
│ Requirement, Jira, Figma, Test Design, Export      │
└─────────────────────────┬─────────────────────────┘
                          │
                 ┌────────▼─────────┐
                 │ LangGraph Nodes  │
                 └────────┬─────────┘
                          │
                 ┌────────▼─────────┐
                 │ LLM Router       │
                 └───────┬──────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼────────┐              ┌─────────▼─────────┐
│ DeepSeek       │              │ Local AI / Ollama │
│ Remote LLM     │              │ Text / Vision     │
└────────────────┘              └───────────────────┘
```

---

## 4. Project Structure

```text
qa-ai-platform/
│
├── api/
│   └── main.py                    # FastAPI entrypoint
│
├── app/
│   ├── application/               # Application-level orchestration
│   ├── config/                    # Environment loader / config helpers
│   ├── exporters/                 # Excel exporters
│   ├── models/                    # Shared state/data models
│   ├── services/                  # Business services
│   ├── utils/                     # Utility functions
│   └── web/                       # Web Portal routes/templates
│
├── bot/
│   ├── telegram_bot.py            # Telegram bot entrypoint
│   ├── handlers/
│   ├── keyboards/
│   └── renderers/
│
├── graph/
│   ├── nodes/                     # LangGraph nodes
│   └── workflows/                 # Graph/workflow definitions
│
├── docs/                          # Documentation
├── prompts/                       # Prompt templates
├── runtime/                       # Runtime jobs and temporary metadata
├── tests/                         # Tests
├── requirements/                  # Generated requirement artifacts
├── reports/                       # Reports
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

---

## 5. Prerequisites

Required:

* Python 3.11+
* Windows PowerShell or compatible terminal
* DeepSeek API key or Local AI/Ollama server
* Jira PAT if using Jira import/sync
* Figma access token if using Figma extraction
* Telegram Bot token if using Telegram Bot

Optional:

* Ollama server for Local AI.
* Qwen text model for local text reasoning.
* Qwen-VL model for local vision analysis.

---

## 6. Installation

```powershell
git clone https://github.com/hoangduong2002/qa-ai-platform.git
cd qa-ai-platform

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

For development dependencies:

```powershell
pip install -r requirements-dev.txt
```

---

## 7. Environment Configuration

Create `.env` from the template:

```powershell
copy .env.example .env
```

Create `.env.secrets` for real API keys and tokens:

```powershell
New-Item .env.secrets -ItemType File
```

Recommended rule:

```text
.env          = non-secret runtime configuration
.env.secrets  = API keys, tokens, credentials only
.env.example  = safe template committed to Git
```

Do not commit `.env` or `.env.secrets`.

If they were already tracked:

```powershell
git rm --cached .env
git rm --cached .env.secrets
```

---

## 8. Environment Loading Order

The platform loads environment files in this order:

```text
1. .env
2. .env.secrets
```

`.env.secrets` is loaded after `.env`, so it may override `.env`.

For safety, `.env.secrets` should only contain secret keys such as:

```env
DEEPSEEK_API_KEY=
TELEGRAM_BOT_TOKEN=
FIGMA_ACCESS_TOKEN=
JIRA_PAT=
JIRA_API_TOKEN=
JIRA_USERNAME=
JIRA_PASSWORD=
GITHUB_TOKEN=
```

Avoid putting runtime config in `.env.secrets`, for example:

```env
DEEPSEEK_MODEL=
LOCAL_BASE_URL=
TELEGRAM_AI_MODE=
PORTAL_DEFAULT_AI_MODE=
ALLOW_DEEPSEEK_PRO=
```

---

## 9. AI Modes

AI Mode controls provider routing. Provider config only defines endpoint and model.

Supported modes:

| Mode                | Description                                                                  |
| ------------------- | ---------------------------------------------------------------------------- |
| `PRODUCTION_HYBRID` | DeepSeek for text/reasoning. Local/Ollama for compact/vision when available. |
| `DEEPSEEK_ONLY`     | DeepSeek for text/reasoning. Local vision is skipped.                        |
| `TEST_LOCAL_ONLY`   | Local/Ollama only. Never call DeepSeek.                                      |
| `NO_LLM`            | No LLM calls. Import/extract/rule-based operations only.                     |

Typical config:

```env
TELEGRAM_AI_MODE=PRODUCTION_HYBRID
PORTAL_DEFAULT_AI_MODE=NO_LLM
NON_PORTAL_AI_MODE=
```

Recommended behavior:

```text
Telegram:
  TELEGRAM_AI_MODE controls Telegram flows.

Web Portal:
  Portal UI sends X-AI-Mode.
  PORTAL_DEFAULT_AI_MODE is used when no UI mode is selected.

CLI / scripts:
  NON_PORTAL_AI_MODE can be used as fallback.
```

---

## 10. DeepSeek Configuration

Default remote model should be Flash, not Pro:

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=120
ALLOW_DEEPSEEK_PRO=false
FORCE_DISABLE_DEEPSEEK=false
```

`deepseek-v4-pro` is intentionally protected by a cost guard.

Use Pro only when you intentionally want it:

```env
DEEPSEEK_MODEL=deepseek-v4-pro
ALLOW_DEEPSEEK_PRO=true
```

Recommended default:

```env
DEEPSEEK_MODEL=deepseek-v4-flash
ALLOW_DEEPSEEK_PRO=false
```

---

## 11. Local AI / Ollama Configuration

Local AI means an Ollama server reachable from the application.

It can run:

* On the same machine.
* On another machine in LAN.

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

For LAN Ollama:

```env
LOCAL_BASE_URL=http://<LAN_IP>:11434
```

Example:

```env
LOCAL_BASE_URL=http://192.168.1.50:11434
```

Check connectivity:

```powershell
Invoke-RestMethod http://<LAN_IP>:11434/api/tags
```

If Ollama runs on another Windows machine, make sure:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
```

Then restart Ollama and allow firewall port `11434`.

---

## 12. Image Analysis Policy

Tesseract OCR has been removed from the platform.

Image analysis uses Local Vision through `LOCAL_VISION_MODEL` only when selected AI mode allows Local Vision.

| AI Mode             | Vision Behavior                                |
| ------------------- | ---------------------------------------------- |
| `PRODUCTION_HYBRID` | Use Local Vision if available, otherwise skip. |
| `TEST_LOCAL_ONLY`   | Use Local Vision if available.                 |
| `DEEPSEEK_ONLY`     | Skip vision.                                   |
| `NO_LLM`            | Skip vision.                                   |

There is no fallback to Tesseract.

There is no fallback to DeepSeek for images.

---

## 13. Jira Configuration

```env
JIRA_SERVER_URL=https://your-jira-server
JIRA_AUTH_MODE=PAT
JIRA_VERIFY_SSL=true
JIRA_INCLUDE_SUBTASKS=true
```

Supported auth modes:

```env
JIRA_AUTH_MODE=PAT
```

Use:

```env
JIRA_PAT=
```

or:

```env
JIRA_AUTH_MODE=BASIC
JIRA_USERNAME=
JIRA_API_TOKEN=
```

`JIRA_SERVER_URL` is the canonical Jira base URL key.

---

## 14. Figma Configuration

```env
FIGMA_ENABLE_EXTRACTION=false
FIGMA_EXTRACT_SCOPE=linked_page
FIGMA_ALLOW_FIRST_PAGE_FALLBACK=false

FIGMA_MAX_FILES_PER_TICKET=5
FIGMA_MAX_LAYERS_PER_PAGE=30
FIGMA_MAX_SCREENS_PER_LAYER=50
FIGMA_MAX_SCREENS_PER_PAGE=100

FIGMA_PAGE_RESOLVE_DEPTH=4
FIGMA_PAGE_FETCH_DEPTH=3
FIGMA_LAYER_FETCH_DEPTH=4
FIGMA_LAYER_SCAN_DEPTH=3

FIGMA_IMAGE_EXPORT_BATCH_SIZE=1
FIGMA_EXPORT_SCALE=1
FIGMA_EXPORT_FORMAT=png
FIGMA_EXPORT_CONTAINER_LAYERS=false
```

Figma behavior:

```text
Figma link
  ↓
Resolve file/page/node
  ↓
Extract SECTION containers
  ↓
Export FRAME screens
  ↓
Save frame.png and screen_context.md
  ↓
Run Local Vision if AI mode allows it
  ↓
Otherwise write skipped marker
```

---

## 15. Requirement Handling Configuration

```env
SANITIZE_REQUIREMENT=true
REDACT_EMAILS=true
REDACT_USERS=true
REDACT_ORGANIZATIONS=true
REDACT_URLS=true

REQUIREMENT_CHUNK_MAX_CHARS=20000
REQUIREMENT_COMPACT_CONTEXT_MAX_CHARS=60000
```

Compact context limits:

```env
REQUIREMENT_COMPACT_MAX_TEXT_ITEMS_PER_SCREEN=10
REQUIREMENT_COMPACT_MAX_SCREEN_NAMES_PER_SECTION=20
REQUIREMENT_COMPACT_MAX_KEY_TEXTS_PER_SECTION=20
REQUIREMENT_COMPACT_MAX_ACTIONS_PER_SECTION=10
REQUIREMENT_COMPACT_MAX_QA_NOTES_PER_SECTION=10
REQUIREMENT_COMPACT_MAX_SCREENS_PER_SECTION_IN_MARKDOWN=50
```

---

## 16. Generation Configuration

```env
IMPROVE_FAIL_FAST=false

TESTCASE_PARALLEL_WORKERS=2
TESTCASE_SCENARIO_BATCH_SIZE=5
TESTCASE_BATCH_PARALLEL_WORKERS=2

MAX_STRUCTURE_REVIEW_ITERATIONS=3

SCENARIO_STRUCTURE_BATCH_SIZE=5
SCENARIO_PARALLEL_WORKERS=2

INCREMENTAL_MAJOR_CHANGE_THRESHOLD=0.35
```

For safer DeepSeek cost and fewer concurrency errors:

```env
TESTCASE_PARALLEL_WORKERS=1
TESTCASE_BATCH_PARALLEL_WORKERS=1
SCENARIO_PARALLEL_WORKERS=1
```

---

## 17. LLM Cost and Concurrency Safety

Recommended:

```env
MAX_DEEPSEEK_CALLS_PER_JOB=20
MAX_DEEPSEEK_INPUT_TOKENS_PER_JOB=300000
MAX_DEEPSEEK_OUTPUT_TOKENS_PER_JOB=100000

MAX_CONCURRENT_LLM_CALLS=2
MAX_CONCURRENT_DEEPSEEK_CALLS=2
MAX_CONCURRENT_LOCAL_CALLS=1

LLM_CONCURRENCY_WAIT_TIMEOUT=300
LLM_CONCURRENCY_RETRY_COUNT=3
LLM_CONCURRENCY_RETRY_DELAY_SECONDS=10

AI_DRY_RUN=false
```

If too many LLM calls run in parallel, reduce:

```env
TESTCASE_PARALLEL_WORKERS=1
TESTCASE_BATCH_PARALLEL_WORKERS=1
```

---

## 18. Run Web Portal

Start FastAPI:

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

Common Portal actions:

* Create manual requirement.
* Create requirement from Jira.
* Sanitize requirement.
* Analyze requirement.
* Answer clarifications.
* Generate requirement summary.
* Generate / review / approve test structure.
* Generate scenarios.
* Review / improve / approve scenarios.
* Generate test cases.
* Review / improve / approve test cases.
* Export Excel files.
* Sync Jira changes.
* Build regeneration plan.
* Run incremental analyze/scenario/testcase generation.

---

## 19. Run Telegram Bot

```powershell
python -m bot.telegram_bot
```

Root-level `telegram_bot.py` is legacy. Prefer:

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

Generate test cases from existing requirement. If the ID looks like Jira and no local requirement exists, the bot can create the requirement from Jira first.

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

---

## 20. Jira Change Sync Flow

Jira sync is available only for requirements imported from Jira.

High-level flow:

```text
Jira Requirement
  ↓
Initial Jira Snapshot
  ↓
Sync Jira Changes
  ↓
Compare Old Snapshot vs New Snapshot
  ↓
Change Impact Report
  ↓
Build Regeneration Plan
  ↓
Safety Gate
  ↓
Incremental Requirement Analysis
  ↓
Incremental Scenario Generation
  ↓
Incremental Test Case Generation
  ↓
Merge / Export Incremental Excel
```

The Portal hides or blocks Jira sync actions for non-Jira requirements.

If a requirement was created manually, Jira sync is not available.

---

## 21. Clarification Flow

```text
Analyze Requirement
  ↓
Generate Clarification Questions
  ↓
User Answers Clarifications
  ↓
Save Clarification Answers
  ↓
Mark Summary as Outdated
  ↓
Regenerate Summary if needed
```

Clarification answers should be saved and rendered back in the Portal.

Excel export should include both clarification questions and saved answers.

---

## 22. Generated Artifacts

Typical artifact folder:

```text
requirements/<TICKET_ID>/
│
├── source/
│   ├── jira_issue.json
│   ├── jira_requirement.md
│   └── figma/
│
├── analysis/
│   ├── sanitized_requirement.md
│   ├── requirement_analysis.json
│   ├── clarifications.json
│   ├── clarification_answers.json
│   └── requirement_summary.json
│
├── snapshots/
│   ├── latest_jira_snapshot.json
│   └── jira_snapshot_v*.json
│
├── testcases/
│   ├── scenarios_v*.json
│   ├── testcases_v*.json
│   └── functions/
│
├── exports/
│   └── *.xlsx
│
└── logs/
```

---

## 23. Running Tests

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

---

## 24. Troubleshooting

### DeepSeek model unexpectedly uses Pro

Check effective environment:

```powershell
python -c "from app.config.env_loader import load_project_env; import os; load_project_env(); print('DEEPSEEK_MODEL=', os.getenv('DEEPSEEK_MODEL')); print('ALLOW_DEEPSEEK_PRO=', os.getenv('ALLOW_DEEPSEEK_PRO'))"
```

Expected:

```text
DEEPSEEK_MODEL= deepseek-v4-flash
ALLOW_DEEPSEEK_PRO= false
```

If it shows `deepseek-v4-pro`, check `.env.secrets` and Windows environment variables.

---

### Local AI timeout

If you see:

```text
Connection to <LOCAL_BASE_URL> timed out
```

Check:

```powershell
Invoke-RestMethod http://<LOCAL_IP>:11434/api/tags
```

Also verify:

```env
LOCAL_BASE_URL=http://<correct-ip>:11434
```

Restart server after editing `.env`.

---

### Portal still uses old environment value

Stop all Python processes:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

Then restart FastAPI.

Also confirm you are editing the same project folder that is running:

```powershell
pwd
Get-Content .env | Select-String -Pattern "LOCAL_BASE_URL|DEEPSEEK_MODEL|PORTAL_DEFAULT_AI_MODE"
```

---

### LLM concurrency limit reached

Reduce workers:

```env
TESTCASE_PARALLEL_WORKERS=1
TESTCASE_BATCH_PARALLEL_WORKERS=1
SCENARIO_PARALLEL_WORKERS=1
```

Then restart the server.

---

### Jira sync button appears for non-Jira requirement

Jira sync should only be available when:

```text
requirement source is Jira
and Jira snapshot exists
```

If it appears for manual requirements, check requirement source metadata and Portal template conditions.

---

## 25. Git Hygiene

Do not commit local secrets:

```gitignore
.env
.env.*
!.env.example
```

If `.env.secrets` or `.env` was accidentally pushed, rotate tokens immediately:

* DeepSeek API key.
* Telegram Bot token.
* Jira PAT.
* Figma access token.

---

## 26. Development Notes

Recommended principles:

* Telegram should remain a thin adapter.
* Web Portal should remain a UI adapter.
* Business logic should live in `app/services`.
* LangGraph nodes should focus on workflow steps.
* LLM calls should go through `llm_router_service`.
* Do not call DeepSeek directly from Portal/Telegram code.
* Do not use Tesseract.
* Do not fallback to DeepSeek for image analysis.
* Prefer explicit `ai_mode` and `source_channel` in workflow state.
* Avoid hidden fallback to `NO_LLM` for Telegram or Portal flows.
* Use cost guard for expensive models.

---

## 27. Roadmap

### Current

* Requirement analysis.
* Clarification generation.
* Requirement summary.
* Web Portal.
* Telegram Bot.
* Jira import.
* Figma extraction.
* Test structure generation/review/approval.
* Scenario generation/review/approval.
* Test case generation/review/approval.
* Coverage review.
* Excel export.
* Jira sync and incremental regeneration.

### Next

* Improve regeneration plan accuracy.
* Strengthen traceability matrix.
* Improve clarification answer merge and export.
* Add better job progress tracking.
* Add provider health check page.
* Add Teams integration.
* Add AI evaluation metrics.
* Add risk-based test prioritization.

---

## 28. License

Internal project.

```
```
