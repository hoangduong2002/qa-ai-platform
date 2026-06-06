# QA AI Platform

AI-powered Requirement Analysis and Test Case Generation Platform

---

# Overview

QA AI Platform is an AI-assisted system that helps QA teams transform requirements into structured test assets.

The platform supports:

* Requirement Analysis
* Clarification Question Generation
* Requirement Refinement
* Test Scope Definition
* Scenario Generation
* Test Case Generation
* Coverage Review
* AI-assisted Test Case Improvement
* Traceability Matrix
* Excel Export
* Requirement Lifecycle Management

The platform is designed to reduce manual effort in test design while improving requirement coverage and traceability.

---

# Business Goal

Traditional test design activities are time-consuming and heavily dependent on QA experience.

QA AI Platform aims to:

* Accelerate test design
* Improve requirement coverage
* Reduce missed test scenarios
* Improve traceability
* Standardize QA outputs
* Enable requirement refinement before implementation
* Support QA teams without requiring AI expertise

---

# Current Features

## Requirement Management

* Create requirement from text
* Create requirement from Jira ticket
* Upload supporting documents
* Add additional notes
* Rename requirement
* Delete requirement
* List all requirements
* Requirement status tracking

## Supported Requirement Sources

### Text

```text
/generate_text
```

### Jira

```text
/generate TICKET-ID
```

### Documents

Supported formats:

* TXT
* MD
* DOCX
* PPTX
* PNG
* JPG
* WEBP

---

# Requirement Intelligence

## Requirement Analysis

Extract:

* Actors
* Functional Requirements
* Business Rules
* Validations
* Dependencies
* Risks
* Missing Information

Generate stable requirement IDs:

```text
FR001
BR001
VAL001
DEP001
```

---

## Clarification Generation

Automatically identify:

* Missing business rules
* Validation gaps
* Edge cases
* Security concerns
* Error handling gaps
* Integration questions

Example:

```text
Q001
What is the maximum allowed email length?
```

---

## Clarification Answers

Users can answer clarification questions.

Answers become part of the requirement source.

Example:

```text
Q001: 255 characters
```

The platform automatically:

* Updates requirement knowledge
* Regenerates analysis
* Avoids asking the same question again

---

## Requirement Summary

Creates consolidated requirement knowledge including:

* Executive Summary
* Functional Summary
* Confirmed Business Rules
* Validation Rules
* Open Questions
* Assumptions
* Risks

---

# Test Design Workflow

```text
Requirement
    ↓
Requirement Analysis
    ↓
Clarification Generation
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
Final Coverage Review
    ↓
Excel Export
```

---

# Traceability

The platform supports:

```text
Requirement
    ↓
Scenario
    ↓
Test Case
```

Each artifact contains:

### Requirement IDs

```text
FR001
BR001
VAL001
```

### Scenario IDs

```text
SC001
SC002
```

### Test Case IDs

```text
TC001
TC002
```

---

# Excel Export

Generated workbook contains:

## Requirements

Requirement inventory

## Clarifications

Questions
Answers
Status

## Requirement Summary

Business view

## Scenarios

Scenario inventory

## Test Cases

Generated test cases

## Requirement Coverage Matrix

Requirement → Scenario → Test Case mapping

---

# AI Architecture

## Core Framework

* LangGraph
* LangChain

## API

* FastAPI

## Bot Interface

* Telegram Bot

Future:

* Microsoft Teams

---

# LLM Providers

Supported:

## DeepSeek

```env
LLM_PROVIDER=DEEPSEEK
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=xxxx
```

## Local Enterprise Gateway

```env
LLM_PROVIDER=LOCAL

LOCAL_LLM_URL=http://localhost:xxxx/v1/chat/completions

LOCAL_LLM_MODEL=claude-sonnet-4.6
```

Example payload:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Generate test cases"
    }
  ],
  "model": "claude-sonnet-4.6"
}
```

---

# Project Structure

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

# Installation

## Python

Recommended:

```text
Python 3.11+
```

## Create Virtual Environment

```powershell
python -m venv .venv
```

Activate:

```powershell
.venv\Scripts\activate
```

## Install Dependencies

```powershell
pip install -r requirements.txt
```

---

# Configuration

Create:

```text
.env
```

Example:

```env
LLM_PROVIDER=DEEPSEEK

DEEPSEEK_API_KEY=xxxxx

DEEPSEEK_MODEL=deepseek-v4-flash

TELEGRAM_BOT_TOKEN=xxxxx
```

---

# Run Telegram Bot

```powershell
python -m bot.telegram_bot
```

---

# Available Commands

## Create Requirement

```text
/generate_text
```

## Analyze Requirement

```text
/analyze <ticket_id>
```

## Generate Test Cases

```text
/generate <ticket_id>
```

## Requirement Status

```text
/status <ticket_id>
```

## List Requirements

```text
/requirements
```

## Add Additional Notes

```text
/add_text <ticket_id>
```

## Rename Requirement

```text
/rename <ticket_id>
```

## Delete Requirement

```text
/delete <ticket_id>
```

## Delete All Requirements

```text
/delete_all
```

## AI Usage Report

```text
/report
```

---

# Metrics & Reporting

The platform tracks:

* Number of requirements
* Number of scenarios
* Number of test cases
* Number of improvements
* AI requests
* AI models used
* Token consumption
* Processing duration
* Requirement lifecycle status

---

# Roadmap

## MVP1 (Completed)

* Requirement Analysis
* Clarifications
* Requirement Summary
* Test Scope
* Scenario Generation
* Test Case Generation
* Excel Export
* Coverage Review
* Improve Test Cases
* Traceability Matrix
* Telegram Integration

## MVP2

* Jira Integration Enhancement
* Requirement Change Impact Analysis
* Multi-file Requirement Intelligence
* AI Test Data Generation
* Test Suite Optimization
* Teams Integration
* Requirement Knowledge Base

## MVP3

* Auto Jira Sync
* Test Execution Recommendation
* Defect Prediction
* Risk-based Testing
* Regression Impact Analysis
* Multi-agent QA Copilot

---

# Future Vision

Build an enterprise-grade QA AI platform that can:

* Understand requirements
* Identify gaps
* Design test coverage
* Improve test quality
* Maintain traceability
* Assist QA teams throughout the SDLC

while keeping humans in control of final decisions.
