# QA AI Platform

AI-powered Requirement Analysis and Test Case Generation Platform

---

# 🚀 Quick Start

## Prerequisites

* Python 3.11+
* Telegram Bot Token
* DeepSeek API Key or Local LLM Gateway

## Installation

```powershell
git clone <repository>

cd qa-ai-platform

python -m venv .venv

.venv\Scripts\activate

pip install -r requirements.txt
```

---

## Configuration

Create local configuration from the safe template:

```powershell
copy .env.example .env
```

Put real API keys and tokens in `.env.secrets`:

```env
DEEPSEEK_API_KEY=
TELEGRAM_BOT_TOKEN=
JIRA_PAT=
FIGMA_ACCESS_TOKEN=
```

Environment files are loaded in this order:

1. `.env`
2. `.env.secrets`

`.env.secrets` is loaded last and can override `.env`.

Do not commit `.env` or `.env.secrets`. If either file was already tracked,
remove it from Git tracking without deleting your local copy:

```powershell
git rm --cached .env
git rm --cached .env.secrets
```

---

## Run Telegram Bot

```powershell
python -m bot.telegram_bot
```

Use `python -m bot.telegram_bot`. Root-level `telegram_bot.py` is legacy.

Telegram LLM tasks default to:

```env
TELEGRAM_AI_MODE=PRODUCTION_HYBRID
```

Supported Telegram modes: `PRODUCTION_HYBRID`, `TEST_LOCAL_ONLY`, `DEEPSEEK_ONLY`.

---

## Verify LLM Connection

```powershell
python test_llm.py
```

---

# 📱 Available Commands

## Requirement Creation

```text
/generate_text
```

Create requirement from text.

---

```text
/generate <ticket_id>
```

Generate test cases from an existing requirement. If the ID looks like a Jira
issue key and no local requirement exists, the bot creates the requirement from
Jira first.

---

```text
/generate_jira <issue_key>
```

Create requirement from Jira, analyze clarifications, then continue generation.

---

## Requirement Analysis

```text
/analyze <ticket_id>
```

Run:

* Requirement Analysis
* Clarification Generation
* Requirement Summary

---

## Requirement Management

```text
/requirements
```

List requirements.

```text
/status <ticket_id>
```

Show status.

```text
/rename <ticket_id>
```

Rename requirement.

```text
/delete <ticket_id>
```

Delete requirement.

```text
/delete_all
```

Delete all requirements.

---

## Requirement Refinement

```text
/add_text <ticket_id>
```

Add additional requirement notes.

---

## Reporting

```text
/report
```

Show:

* AI usage
* Token usage
* Processing time
* Generated assets

---

# 🎯 Business Overview

QA AI Platform helps QA teams:

* Analyze requirements
* Identify requirement gaps
* Generate clarification questions
* Build test coverage
* Generate test cases
* Maintain traceability
* Improve test quality

Goal:

```text
Requirement
    ↓
Coverage
    ↓
Quality Test Cases
```

---

# ✨ Core Features

## Requirement Intelligence

* Requirement Analysis
* Requirement Items
* Clarifications
* Requirement Summary

## Test Design

* Test Scope Generation
* Scenario Generation
* Test Case Generation

## Quality Review

* Coverage Review
* Test Case Improvement
* Final Coverage Review

## Traceability

```text
Requirement
    ↓
Scenario
    ↓
Test Case
```

## Export

* Excel Export
* Coverage Matrix

---

# 🏗 System Architecture

## Main Components

```text
Telegram Bot
      ↓
FastAPI
      ↓
LangGraph Workflow
      ↓
LLM Provider
      ↓
Requirement Artifacts
```

See:

* Architecture Diagram.md
* Requirement Lifecycle State Machine.md

---

# 🔄 Workflow

```text
Requirement
    ↓
Requirement Analysis
    ↓
Clarification Questions
    ↓
Requirement Summary
    ↓
Test Scope
    ↓
Scenario Generation
    ↓
Test Case Generation
    ↓
Coverage Review
    ↓
Improve Test Cases
    ↓
Final Review
    ↓
Excel Export
```

---

# 📂 Project Structure

```text
qa-ai-platform
│
├── app
│   ├── services
│   ├── utils
│   ├── prompts
│
├── graph
│   ├── nodes
│   ├── workflows
│
├── bot
│
├── requirements
│
├── exports
│
└── tests
```

---

# 🤖 Supported LLM Providers

## DeepSeek

```env
LLM_PROVIDER=DEEPSEEK
DEEPSEEK_MODEL=deepseek-v4-flash
```

## Local Enterprise Gateway

```env
LLM_PROVIDER=LOCAL

LOCAL_LLM_URL=http://localhost:xxxx/v1/chat/completions

LOCAL_LLM_MODEL=claude-sonnet-4.6
```

---

# 📊 Metrics & Reporting

Tracked metrics:

* Requirements generated
* Scenarios generated
* Test cases generated
* Improvement cycles
* AI requests
* Model usage
* Token consumption
* Processing duration

---

# 🗺 Roadmap

## MVP1 (Current)

✅ Requirement Analysis

✅ Clarifications

✅ Requirement Summary

✅ Test Scope

✅ Scenario Generation

✅ Test Case Generation

✅ Coverage Review

✅ Improve Test Cases

✅ Traceability Matrix

✅ Excel Export

✅ Telegram Integration

---

## MVP2

* Enhanced Jira Integration
* Requirement Change Impact Analysis
* AI Test Data Generation
* Teams Integration
* Knowledge Base

---

## MVP3

* Auto Jira Synchronization
* Risk-based Testing
* Regression Impact Analysis
* Multi-Agent QA Copilot

---

# 📄 Documentation

Additional documents:

* README.md
* Architecture Diagram.md
* Requirement Lifecycle State Machine.md
* Security Policy.md
* MVP Roadmap.md

---

# 📜 License

Internal project.
