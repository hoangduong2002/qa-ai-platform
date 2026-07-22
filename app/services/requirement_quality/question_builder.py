from __future__ import annotations

from app.services.requirement_quality.models import QualityIssue, SuggestedClarificationQuestion


def build_question(issue: QualityIssue, index: int) -> SuggestedClarificationQuestion:
    return SuggestedClarificationQuestion(
        question_id=f"Q2-{index:03d}",
        issue_id=issue.issue_id,
        question=issue.proposed_question,
        affected_field=issue.affected_field,
        severity=issue.severity,
        source_references=issue.source_references,
    )


def build_questions(issues: list[QualityIssue]) -> list[SuggestedClarificationQuestion]:
    return [
        build_question(issue, index)
        for index, issue in enumerate(issues, start=1)
        if issue.proposed_question.strip()
    ]
