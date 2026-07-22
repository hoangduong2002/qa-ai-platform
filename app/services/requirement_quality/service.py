from __future__ import annotations

from typing import Any

from app.services.requirement_quality.config import quality_gate_enabled, quality_gate_mode
from app.services.requirement_quality.llm_review import review_quality_with_llm
from app.services.requirement_quality.models import (
    QualityGateMode,
    QualityIssue,
    QualityIssueType,
    QualitySeverity,
    RequirementQualityReportV1,
    StructuredAnalysisValidationError,
)
from app.services.requirement_quality.question_builder import build_questions
from app.services.requirement_quality.rules import run_deterministic_quality_checks
from app.services.requirement_quality.writer import (
    save_clarification_questions_v2,
    save_quality_error,
    save_quality_report,
)


def _score_from_issues(issues: list[QualityIssue]) -> int:
    score = 100
    for issue in issues:
        if issue.severity == QualitySeverity.BLOCKER:
            score -= 25
        elif issue.severity == QualitySeverity.WARNING:
            score -= 10
        else:
            score -= 3
    return max(score, 0)


def _validate_structured_analysis_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise StructuredAnalysisValidationError("structured_analysis must be a JSON object")

    required_fields = [
        "business_rules",
        "expected_results",
        "ambiguities",
        "contradictions",
        "missing_information",
    ]

    for field in required_fields:
        value = payload.get(field)
        if value is None:
            raise StructuredAnalysisValidationError(f"structured_analysis missing field: {field}")
        if not isinstance(value, list):
            raise StructuredAnalysisValidationError(f"structured_analysis field must be a list: {field}")

    return payload


def _make_issue_from_llm_warning(item: dict, index: int) -> QualityIssue | None:
    if not isinstance(item, dict):
        return None

    question = str(item.get("proposed_question", "")).strip()
    explanation = str(item.get("explanation", "")).strip()
    affected = str(item.get("affected_field", "analysis")).strip() or "analysis"

    if not question or not explanation:
        return None

    evidence = item.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    return QualityIssue(
        issue_id=f"QG-LLM-{index:03d}",
        issue_type=QualityIssueType.CLARITY,
        severity=QualitySeverity.WARNING,
        affected_field=affected,
        explanation=explanation,
        evidence=[str(entry) for entry in evidence],
        source_references=[],
        proposed_question=question,
        kb_retrieval_could_help=bool(item.get("kb_retrieval_could_help", False)),
        human_confirmation_mandatory=bool(item.get("human_confirmation_mandatory", True)),
    )


def run_requirement_quality_gate(
    *,
    ticket_id: str,
    structured_analysis: dict | None,
    ai_mode: str | None = None,
) -> dict:
    mode = quality_gate_mode()
    enabled = quality_gate_enabled() and mode != QualityGateMode.OFF

    if not enabled:
        return {
            "enabled": False,
            "mode": mode.value,
            "quality_report": None,
            "clarification_questions_v2": None,
            "error": None,
            "blocking": False,
        }

    try:
        validated = _validate_structured_analysis_payload(structured_analysis)
        issues = run_deterministic_quality_checks(validated)

        # Optional additive LLM review remains secondary to deterministic checks.
        llm_review = review_quality_with_llm(
            ai_mode=ai_mode,
            structured_analysis=validated,
            deterministic_report={
                "issues": [item.model_dump(mode="json") for item in issues],
            },
        )

        additional = []
        for index, warning in enumerate(llm_review.get("additional_warnings", []), start=1):
            issue = _make_issue_from_llm_warning(warning, index)
            if issue:
                additional.append(issue)

        all_issues = issues + additional

        blocking_issues = [item for item in all_issues if item.severity == QualitySeverity.BLOCKER]
        warnings = [item for item in all_issues if item.severity == QualitySeverity.WARNING]
        ambiguities = [item for item in all_issues if item.issue_type == QualityIssueType.CLARITY]
        contradictions = [item for item in all_issues if item.issue_type in {QualityIssueType.CONTRADICTION, QualityIssueType.CONSISTENCY}]
        missing_information = [item for item in all_issues if item.issue_type == QualityIssueType.MISSING_INFORMATION]

        questions = build_questions(all_issues)

        ready_for_test_design = len(blocking_issues) == 0
        report = RequirementQualityReportV1(
            schema_version="1.0",
            mode=mode,
            score=_score_from_issues(all_issues),
            ready_for_test_design=ready_for_test_design,
            blocking_issues=blocking_issues,
            warnings=warnings,
            ambiguities=ambiguities,
            contradictions=contradictions,
            missing_information=missing_information,
            suggested_clarification_questions=questions,
            source_references=[],
        )

        report_dict = report.model_dump(mode="json")

        save_quality_report(ticket_id, report_dict)
        save_clarification_questions_v2(
            ticket_id,
            {
                "schema_version": "1.0",
                "ticket_id": ticket_id,
                "questions": [item.model_dump(mode="json") for item in questions],
            },
        )

        blocking = bool(blocking_issues) and mode == QualityGateMode.BLOCK_ON_CRITICAL

        return {
            "enabled": True,
            "mode": mode.value,
            "quality_report": report_dict,
            "clarification_questions_v2": {
                "schema_version": "1.0",
                "ticket_id": ticket_id,
                "questions": [item.model_dump(mode="json") for item in questions],
            },
            "error": None,
            "blocking": blocking,
        }

    except Exception as error:
        save_quality_error(ticket_id, str(error))
        return {
            "enabled": True,
            "mode": mode.value,
            "quality_report": None,
            "clarification_questions_v2": None,
            "error": str(error),
            "blocking": False,
        }
