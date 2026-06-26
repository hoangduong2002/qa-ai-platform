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
New-Item .env.secrets -ItemType File
````

Update `.env` and `.env.secrets`, then run Web Portal:

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

## 4. Required Environment Values

At minimum, configure one AI provider.

### 4.1 DeepSeek

Use this when running `PRODUCTION_HYBRID` or `DEEPSEEK_ONLY`.

`.env`:

```env
TELEGRAM_AI_MODE=PRODUCTION_HYBRID
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

### 4.2 Local AI / Ollama

Use this when running `TEST_LOCAL_ONLY` or when `PRODUCTION_HYBRID` needs local compact/vision.

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

### 4.3 Jira

Required when importing or syncing Jira requirements.

`.env`:

```env
JIRA_SERVER_URL=https://your-jira-server
JIRA_AUTH_MODE=PAT
JIRA_VERIFY_SSL=true
JIRA_INCLUDE_SUBTASKS=true
```

`.env.secrets`:

```env
JIRA_PAT=
```

### 4.4 Figma

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

### 4.5 Telegram

Required only when running Telegram Bot.

`.env.secrets`:

```env
TELEGRAM_BOT_TOKEN=
```

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

Use this when the app appears to read old `.env` values.

```powershell
python -c "from app.config.env_loader import load_project_env; import os; load_project_env(); print('PWD=', os.getcwd()); print('TELEGRAM_AI_MODE=', os.getenv('TELEGRAM_AI_MODE')); print('PORTAL_DEFAULT_AI_MODE=', os.getenv('PORTAL_DEFAULT_AI_MODE')); print('DEEPSEEK_MODEL=', os.getenv('DEEPSEEK_MODEL')); print('LOCAL_BASE_URL=', os.getenv('LOCAL_BASE_URL'))"
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
