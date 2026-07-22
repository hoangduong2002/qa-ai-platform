from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services.llm_router_service import (
    TASK_TEST_QUALITY_CORRECTION,
    TASK_TEST_QUALITY_REVIEW,
    call_llm_with_fallback,
)
from app.services.test_case_generator_v2.models import TestCaseSetV2
from app.services.test_case_generator_v2.service import _validate_traceability
from app.services.test_quality_review.config import (
    TestQualityReviewMode,
    corrector_ai_mode,
    corrector_model,
    reviewer_ai_mode,
    reviewer_model,
    test_quality_review_mode,
)
from app.services.test_quality_review.deterministic import run_deterministic_checks
from app.services.test_quality_review.models import (
    CorrectionAttempt,
    CorrectionHistoryV1,
    CorrectionResult,
    ReviewCategory,
    ReviewSeverity,
    ReviewStatus,
    TestQualityIssue,
    TestQualityReportV1,
)
from app.utils.llm_json import parse_json
from app.utils.prompt_loader import load_prompt
from knowledge.storage.utils import atomic_write_json, atomic_write_text, read_json


logger = logging.getLogger(__name__)
MAX_REVIEW_ATTEMPTS = 2


def _design_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "test-design"


def _write_json(path: Path, payload) -> str:
    atomic_write_json(path, payload)
    return str(path)


def _metadata(response, *, profile: str, model_override: str | None) -> dict:
    return {
        "profile": profile,
        "provider": response.provider,
        "model": model_override or response.model,
        "ai_mode": "configured_by_router",
        "fallback_used": response.fallback_used,
        "duration_seconds": round(response.duration_seconds, 4),
    }


def _review_prompt(inputs: dict, testcases: TestCaseSetV2, deterministic: dict, attempt: int) -> str:
    return (
        load_prompt("prompts/review_testcases_v2_quality.md")
        .replace("{review_attempt}", str(attempt))
        .replace("{review_inputs}", json.dumps(inputs, indent=2, ensure_ascii=False))
        .replace(
            "{generated_testcases}",
            json.dumps(testcases.model_dump(mode="json"), indent=2, ensure_ascii=False),
        )
        .replace("{deterministic_findings}", json.dumps(deterministic, indent=2, ensure_ascii=False))
        .replace(
            "{review_schema}",
            json.dumps(TestQualityReportV1.model_json_schema(), indent=2, ensure_ascii=False),
        )
    )


def call_reviewer_llm(
    *,
    inputs: dict,
    testcases: TestCaseSetV2,
    deterministic: dict,
    state: dict,
    attempt: int,
) -> tuple[TestQualityReportV1, dict]:
    model_override = reviewer_model()
    response = call_llm_with_fallback(
        TASK_TEST_QUALITY_REVIEW,
        _review_prompt(inputs, testcases, deterministic, attempt),
        system_prompt=(
            "You are an independent QA test-quality auditor. Do not defer to the "
            "generator's conclusions and never approve unsupported behavior."
        ),
        response_format={"type": "json_object"},
        ai_mode=reviewer_ai_mode(state.get("ai_mode")),
        source_channel=state.get("source_channel"),
        model_override=model_override,
    )
    atomic_write_text(
        _design_dir(inputs["ticket_id"]) / f"test_quality_review_attempt_{attempt}_raw.txt",
        response.content,
    )
    payload = parse_json(response.content, label="test quality review response")
    if not isinstance(payload, dict):
        raise ValueError("Test quality review response must be an object")
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("ticket_id", inputs["ticket_id"])
    payload.setdefault("review_status", "NEEDS_QA_REVIEW")
    payload.setdefault("summary", "Independent test quality review completed.")
    payload.setdefault("issues", [])
    payload.setdefault("missing_coverage", [])
    payload.setdefault("duplicate_groups", [])
    payload.setdefault("correction_instructions", [])
    payload.setdefault("reviewer_version", "phase9-v1")
    payload.setdefault("model_metadata", {})
    payload["review_attempts"] = attempt
    return TestQualityReportV1.model_validate(payload), _metadata(
        response,
        profile="independent-reviewer",
        model_override=model_override,
    )


def _correction_prompt(
    inputs: dict,
    testcases: TestCaseSetV2,
    issues: list[TestQualityIssue],
) -> str:
    return (
        load_prompt("prompts/correct_testcases_v2_quality.md")
        .replace("{review_inputs}", json.dumps(inputs, indent=2, ensure_ascii=False))
        .replace(
            "{generated_testcases}",
            json.dumps(testcases.model_dump(mode="json"), indent=2, ensure_ascii=False),
        )
        .replace(
            "{correction_issues}",
            json.dumps([item.model_dump(mode="json") for item in issues], indent=2, ensure_ascii=False),
        )
        .replace(
            "{correction_schema}",
            json.dumps(CorrectionResult.model_json_schema(), indent=2, ensure_ascii=False),
        )
    )


def call_corrector_llm(
    *,
    inputs: dict,
    testcases: TestCaseSetV2,
    issues: list[TestQualityIssue],
    state: dict,
) -> tuple[CorrectionResult, dict]:
    model_override = corrector_model()
    response = call_llm_with_fallback(
        TASK_TEST_QUALITY_CORRECTION,
        _correction_prompt(inputs, testcases, issues),
        system_prompt=(
            "You are a constrained test-case corrector. Modify only affected cases, "
            "preserve valid cases and stable IDs, and never introduce unsupported facts."
        ),
        response_format={"type": "json_object"},
        ai_mode=corrector_ai_mode(state.get("ai_mode")),
        source_channel=state.get("source_channel"),
        model_override=model_override,
    )
    atomic_write_text(
        _design_dir(inputs["ticket_id"]) / "test_quality_correction_raw.txt",
        response.content,
    )
    payload = parse_json(response.content, label="test quality correction response")
    return CorrectionResult.model_validate(payload), _metadata(
        response,
        profile="constrained-corrector",
        model_override=model_override,
    )


def _failure_issue(category: ReviewCategory, explanation: str) -> TestQualityIssue:
    return TestQualityIssue(
        issue_id=f"TQI-{category.value.lower().replace('_', '-')}",
        severity=ReviewSeverity.BLOCKER,
        category=category,
        explanation=explanation,
        recommended_correction="A QA reviewer must inspect the test cases before approval.",
        auto_correctable=False,
        blocks_export=True,
        detected_by="pipeline",
    )


def _combine_issues(
    deterministic: list[TestQualityIssue],
    llm: list[TestQualityIssue],
) -> list[TestQualityIssue]:
    combined = {item.issue_id: item for item in deterministic}
    for item in llm:
        item.detected_by = "llm"
        key = (
            item.category.value,
            item.test_case_id or "",
            " ".join(item.explanation.casefold().split()),
        )
        if any(
            (
                existing.category.value,
                existing.test_case_id or "",
                " ".join(existing.explanation.casefold().split()),
            ) == key
            for existing in combined.values()
        ):
            continue
        combined[item.issue_id] = item
    return list(combined.values())


def _status(issues: list[TestQualityIssue]) -> ReviewStatus:
    if any(item.severity == ReviewSeverity.BLOCKER for item in issues):
        return ReviewStatus.NEEDS_QA_REVIEW
    if issues:
        return ReviewStatus.APPROVED_WITH_WARNINGS
    return ReviewStatus.APPROVED


def _report(
    *,
    ticket_id: str,
    issues: list[TestQualityIssue],
    missing_coverage,
    duplicate_groups,
    attempt: int,
    model_metadata: dict,
) -> TestQualityReportV1:
    blockers = [item for item in issues if item.severity == ReviewSeverity.BLOCKER]
    warnings = [item for item in issues if item.severity == ReviewSeverity.WARNING]
    return TestQualityReportV1(
        ticket_id=ticket_id,
        review_status=_status(issues),
        summary=(
            f"Independent quality review found {len(blockers)} blocker(s), "
            f"{len(warnings)} warning(s), and {len(issues) - len(blockers) - len(warnings)} info issue(s)."
        ),
        issues=issues,
        missing_coverage=missing_coverage,
        duplicate_groups=duplicate_groups,
        correction_instructions=[
            item.recommended_correction for item in issues if item.auto_correctable
        ],
        model_metadata=model_metadata,
        review_attempts=attempt,
    )


def _run_review_attempt(
    *,
    inputs: dict,
    testcases: TestCaseSetV2,
    state: dict,
    attempt: int,
) -> TestQualityReportV1:
    deterministic_issues, missing_coverage, duplicate_groups = run_deterministic_checks(
        testcases, inputs
    )
    deterministic_payload = {
        "issues": [item.model_dump(mode="json") for item in deterministic_issues],
        "missing_coverage": [item.model_dump(mode="json") for item in missing_coverage],
        "duplicate_groups": [item.model_dump(mode="json") for item in duplicate_groups],
    }
    llm_report, metadata = call_reviewer_llm(
        inputs=inputs,
        testcases=testcases,
        deterministic=deterministic_payload,
        state=state,
        attempt=attempt,
    )
    issues = _combine_issues(deterministic_issues, llm_report.issues)
    missing_by_id = {item.coverage_id: item for item in missing_coverage}
    missing_by_id.update({item.coverage_id: item for item in llm_report.missing_coverage})
    groups_by_id = {item.group_id: item for item in duplicate_groups}
    groups_by_id.update({item.group_id: item for item in llm_report.duplicate_groups})
    return _report(
        ticket_id=inputs["ticket_id"],
        issues=issues,
        missing_coverage=list(missing_by_id.values()),
        duplicate_groups=list(groups_by_id.values()),
        attempt=attempt,
        model_metadata=metadata,
    )


def _validate_correction_scope(
    before: TestCaseSetV2,
    correction: CorrectionResult,
    affected_ids: set[str],
    inputs: dict,
) -> None:
    before_by_id = {item.test_case_id: item.model_dump(mode="json") for item in before.test_cases}
    after_by_id = {
        item.test_case_id: item.model_dump(mode="json")
        for item in correction.corrected_testcases.test_cases
    }
    for case_id, original in before_by_id.items():
        if case_id not in affected_ids and after_by_id.get(case_id) != original:
            raise ValueError(f"Corrector modified unaffected case {case_id}")
    changed_ids = {item.test_case_id for item in correction.changes}
    actual_changed = {
        case_id
        for case_id in set(before_by_id) | set(after_by_id)
        if before_by_id.get(case_id) != after_by_id.get(case_id)
    }
    if not actual_changed.issubset(affected_ids):
        raise ValueError(f"Corrector changed cases outside issue scope: {sorted(actual_changed - affected_ids)}")
    if actual_changed - changed_ids:
        raise ValueError(f"Correction history is missing changed cases: {sorted(actual_changed - changed_ids)}")
    _validate_traceability(correction.corrected_testcases, inputs)


def _evaluation_metrics(
    initial: TestQualityReportV1,
    final: TestQualityReportV1,
    correction_attempted: bool,
) -> dict:
    initial_blockers = {item.issue_id for item in initial.issues if item.severity == ReviewSeverity.BLOCKER}
    final_blockers = {item.issue_id for item in final.issues if item.severity == ReviewSeverity.BLOCKER}
    deterministic_blockers = {
        item.issue_id for item in initial.issues
        if item.severity == ReviewSeverity.BLOCKER and item.detected_by == "deterministic"
    }
    new_errors = {item.issue_id for item in final.issues} - {item.issue_id for item in initial.issues}
    return {
        "blocker_precision": round(len(deterministic_blockers) / len(initial_blockers), 4) if initial_blockers else 1.0,
        "unsupported_result_detection": sum(
            item.category in {
                ReviewCategory.UNSUPPORTED_EXPECTED_RESULT,
                ReviewCategory.INVENTED_AMOUNT,
                ReviewCategory.INVENTED_STATUS,
                ReviewCategory.INVENTED_MESSAGE,
                ReviewCategory.INVENTED_CALCULATION,
            }
            for item in initial.issues
        ),
        "duplicate_detection": len(initial.duplicate_groups),
        "missing_coverage_detection": len(initial.missing_coverage),
        "false_blocker_rate": 0.0,
        "correction_success_rate": (
            round(len(initial_blockers - final_blockers) / len(initial_blockers), 4)
            if correction_attempted and initial_blockers else 0.0
        ),
        "new_error_introduction_rate": round(len(new_errors) / max(len(final.issues), 1), 4),
        "qa_acceptance_rate": 0.0,
        "qa_acceptance_sample_size": 0,
    }


def run_test_quality_pipeline(
    *,
    state: dict,
    inputs: dict,
    testcases: TestCaseSetV2,
) -> dict:
    mode = test_quality_review_mode()
    if mode == TestQualityReviewMode.OFF:
        return {
            "reviewed_testcases": testcases,
            "test_quality_review_run": {
                "enabled": False,
                "mode": mode.value,
                "status": "skipped",
                "review_attempts": 0,
            },
        }

    ticket_id = inputs["ticket_id"]
    history = CorrectionHistoryV1(ticket_id=ticket_id)
    current = testcases
    try:
        initial_report = _run_review_attempt(
            inputs=inputs, testcases=current, state=state, attempt=1
        )
    except Exception as error:
        deterministic, missing, groups = run_deterministic_checks(current, inputs)
        deterministic.append(_failure_issue(
            ReviewCategory.REVIEWER_FAILURE,
            f"Independent reviewer failed: {type(error).__name__}: {error}",
        ))
        initial_report = _report(
            ticket_id=ticket_id,
            issues=deterministic,
            missing_coverage=missing,
            duplicate_groups=groups,
            attempt=1,
            model_metadata={"profile": "independent-reviewer", "status": "failed"},
        )
        initial_report.evaluation_metrics = _evaluation_metrics(initial_report, initial_report, False)
        _write_json(_design_dir(ticket_id) / "test_quality_report.json", initial_report.model_dump(mode="json"))
        _write_json(_design_dir(ticket_id) / "correction_history.json", history.model_dump(mode="json"))
        _write_json(_design_dir(ticket_id) / "testcases_v2_reviewed.json", current.model_dump(mode="json"))
        return {
            "reviewed_testcases": current,
            "test_quality_report": initial_report.model_dump(mode="json"),
            "correction_history": history.model_dump(mode="json"),
            "test_quality_review_run": {
                "enabled": True,
                "mode": mode.value,
                "status": "reviewer_failed",
                "review_attempts": 1,
            },
        }

    final_report = initial_report
    correction_attempted = False
    correctable = [
        item
        for item in initial_report.issues
        if item.severity == ReviewSeverity.BLOCKER
        and item.auto_correctable
        and item.test_case_id
    ]
    if correctable:
        correction_attempted = True
        affected_ids = {item.test_case_id for item in correctable if item.test_case_id}
        correction_failure_issue = None
        try:
            correction, correction_metadata = call_corrector_llm(
                inputs=inputs,
                testcases=current,
                issues=correctable,
                state=state,
            )
            _validate_correction_scope(current, correction, affected_ids, inputs)
            current = correction.corrected_testcases
            history.correction_attempts.append(CorrectionAttempt(
                attempt=1,
                status="succeeded",
                affected_test_case_ids=sorted(affected_ids),
                changes=correction.changes,
                model_metadata=correction_metadata,
            ))
        except Exception as error:
            logger.exception("Test quality correction failed. ticket_id=%s", ticket_id)
            history.correction_attempts.append(CorrectionAttempt(
                attempt=1,
                status="failed",
                affected_test_case_ids=sorted(affected_ids),
                error=f"{type(error).__name__}: {error}",
            ))
            correction_failure_issue = _failure_issue(
                ReviewCategory.CORRECTION_FAILURE,
                f"Constrained corrector failed: {type(error).__name__}: {error}",
            )

        try:
            final_report = _run_review_attempt(
                inputs=inputs, testcases=current, state=state, attempt=2
            )
        except Exception as error:
            deterministic, missing, groups = run_deterministic_checks(current, inputs)
            deterministic.append(_failure_issue(
                ReviewCategory.REVIEWER_FAILURE,
                f"Independent reviewer retry failed: {type(error).__name__}: {error}",
            ))
            final_report = _report(
                ticket_id=ticket_id,
                issues=deterministic,
                missing_coverage=missing,
                duplicate_groups=groups,
                attempt=2,
                model_metadata={"profile": "independent-reviewer", "status": "failed"},
            )
        if correction_failure_issue is not None:
            final_report.issues = _combine_issues(
                final_report.issues,
                [correction_failure_issue],
            )
            final_report.review_status = _status(final_report.issues)
            final_report.summary = (
                f"{final_report.summary} The correction attempt failed and requires QA review."
            )

    history.review_attempts = final_report.review_attempts
    final_report.evaluation_metrics = _evaluation_metrics(
        initial_report, final_report, correction_attempted
    )
    _write_json(_design_dir(ticket_id) / "test_quality_report.json", final_report.model_dump(mode="json"))
    _write_json(_design_dir(ticket_id) / "correction_history.json", history.model_dump(mode="json"))
    _write_json(_design_dir(ticket_id) / "testcases_v2_reviewed.json", current.model_dump(mode="json"))
    return {
        "reviewed_testcases": current,
        "test_quality_report": final_report.model_dump(mode="json"),
        "correction_history": history.model_dump(mode="json"),
        "test_quality_review_run": {
            "enabled": True,
            "mode": mode.value,
            "status": final_report.review_status.value,
            "review_attempts": final_report.review_attempts,
            "correction_attempts": len(history.correction_attempts),
        },
    }


def export_is_blocked(ticket_id: str) -> bool:
    if test_quality_review_mode() != TestQualityReviewMode.BLOCK_EXPORT:
        return False
    report = read_json(_design_dir(ticket_id) / "test_quality_report.json", {})
    return str((report or {}).get("review_status") or "") == ReviewStatus.NEEDS_QA_REVIEW.value


def assert_test_quality_export_allowed(ticket_id: str) -> None:
    if export_is_blocked(ticket_id):
        raise ValueError(
            "Test-case export is blocked because the independent quality review still has blockers. "
            "Resolve them or complete QA review first."
        )
