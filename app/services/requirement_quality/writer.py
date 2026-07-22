from __future__ import annotations

import json
from pathlib import Path


def _analysis_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "analysis"


def save_quality_report(ticket_id: str, report: dict) -> str:
    output_file = _analysis_dir(ticket_id) / "quality_report.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(output_file)


def save_clarification_questions_v2(ticket_id: str, payload: dict) -> str:
    output_file = _analysis_dir(ticket_id) / "clarification_questions_v2.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(output_file)


def save_quality_error(ticket_id: str, content: str) -> str:
    output_file = _analysis_dir(ticket_id) / "quality_report_error.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")
    return str(output_file)
