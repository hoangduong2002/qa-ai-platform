QA AI Platform - Project Context
Project Goal

Building an AI-powered QA Test Case Generation Platform.

Current phase: MVP1

Primary interfaces:

Telegram Bot
FastAPI
LangGraph workflow

Main use cases:

Generate test cases from Jira ticket
Generate test cases from free-text requirement
Generate test cases from uploaded files
TXT
DOCX
PPTX
PNG/JPG/WebP
Export test cases to Excel
AI Coverage Review
AI Improve Test Cases
Final Coverage Review
Iterative improvement through Telegram buttons
Current Workflow
Requirement
    ↓
Requirement Analysis
    ↓
Clarification Detection
    ↓
Test Scope Generation
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

LangGraph state contains:

analysis
clarifications
test_scope
scenarios
testcases
coverage_review
improved_testcases
final_coverage_review
Telegram Features Implemented
Commands
/start
/generate <ticket_id>
/generate_text <requirement>
/status <ticket_id>
Upload Files

Telegram supports:

txt
md
docx
pptx
png
jpg
jpeg
webp

Uploaded file flow:

Upload File
    ↓
extract_file_text()
    ↓
create_workspace_from_text()
    ↓
LangGraph
Review Iteration

Implemented:

Improve Again
Accept

Buttons:

🔄 Improve Again
✅ Accept

Maximum:

MAX_ITERATIONS = 3

Stored in:

requirements/<ticket_id>/review/review_session.json

Example:

{
  "improve_iterations": 2,
  "max_iterations": 3,
  "accepted": false
}
Status Command

Implemented:

/status TG-xxxx

Returns:

Scenarios
Testcases
Coverage
Improve Iterations
Accepted
Excel Files

Excel download buttons:

📥 testcases_v0.xlsx
📥 testcases_v1.xlsx
📥 testcases_v2.xlsx
Versioning

Excel:

exports/
    testcases_v0.xlsx
    testcases_v1.xlsx
    testcases_v2.xlsx

Improved Testcases:

testcases/
    improved_testcases.json
    improved_testcases_v1.json
    improved_testcases_v2.json
OCR

Current OCR:

Tesseract OCR

Languages:

eng
fra

Configured:

OCR_LANGUAGE="eng+fra"

OCR used for:

PNG
JPG
WebP
Images extracted from PPTX

Known issue:

LLM OCR normalization may hallucinate Chinese text.

Mitigation:

NO_RELIABLE_TEXT_FOUND

fallback mechanism added.

Future Roadmap
MVP1 Remaining
Better OCR pipeline
Requirement Traceability
Test Case Version Diff
Download Excel from Status
Requirement Clarification Report
Better Scenario Coverage
Review Dashboard
MVP2
Jira Integration
GitHub Integration
GitHub Copilot Chat Integration
GitHub Models Migration
Multi-Agent QA Architecture
Requirement Change Impact Analysis
Regression Suite Generation
Technology Stack

Python

LangGraph

Telegram Bot

FastAPI

OpenPyXL

DeepSeek API

Potential migration:

GitHub Models

Preferred models:

GPT-5 mini
Claude Sonnet 4.6
Gemini 2.5 Pro
Current Request

Please continue helping me build this QA AI Platform from the current state above.