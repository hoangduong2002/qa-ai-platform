import json
from pathlib import Path
from app.utils.review_comment_session import (
    load_review_comments
)
from app.utils.review_comment_session import (
    load_review_comments
)
from app.utils.improvement_history import (
    load_improvement_history
)

def enrich_analysis_with_review_comments(
    analysis: dict,
    review_comments: list
) -> dict:

    analysis = analysis or {}

    requirement_items = list(
        analysis.get(
            "requirement_items",
            []
        )
    )

    existing_ids = {
        item.get("requirement_id")
        for item in requirement_items
    }

    for comment in review_comments:

        comment_id = comment.get(
            "comment_id",
            ""
        )

        if not comment_id:
            continue

        if comment_id in existing_ids:
            continue

        requirement_items.append(
            {
                "requirement_id": comment_id,
                "type": "Review Comment",
                "description": comment.get(
                    "comment",
                    ""
                )
            }
        )

    analysis["requirement_items"] = requirement_items

    return analysis


def load_json_file(file_path: Path, default):
    if not file_path.exists():
        return default

    return json.loads(
        file_path.read_text(
            encoding="utf-8"
        )
    )


def load_text_file(file_path: Path, default: str = "") -> str:
    if not file_path.exists():
        return default

    return file_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )


def load_ticket_artifacts(ticket_id: str):
    root = Path("requirements") / ticket_id

    analysis = load_json_file(
        root / "analysis" / "requirement_analysis.json",
        {}
    )
    
    clarifications = load_json_file(
        root / "analysis" / "clarification_questions_snapshot.json",
        {}
    )

    if not clarifications:
        clarifications = load_json_file(
            root / "analysis" / "clarifications.json",
            {}
        )
    
    clarification_answers = load_json_file(
        root / "analysis" / "clarification_answers.json",
        {}
    )
    
    review_comments = load_review_comments(
        ticket_id
    )
    
    analysis = enrich_analysis_with_review_comments(
        analysis,
        review_comments
    )
    
    requirement_qa = load_json_file(
        root / "analysis" / "requirement_qa.json",
        {}
    )

    structured_analysis = load_json_file(
        root / "analysis" / "structured_analysis.json",
        {}
    )

    quality_report = load_json_file(
        root / "analysis" / "quality_report.json",
        {}
    )

    enriched_analysis = load_json_file(
        root / "analysis" / "enriched_analysis.json",
        {}
    )

    enrichment_diff = load_json_file(
        root / "analysis" / "enrichment_diff.json",
        {}
    )

    enrichment_approval = load_json_file(
        root / "analysis" / "enrichment_approval.json",
        {}
    )

    coverage_model = load_json_file(
        root / "test-design" / "coverage_model.json",
        {}
    )

    coverage_analysis = load_text_file(
        root / "test-design" / "coverage_analysis.md",
        ""
    )

    testcases_v1 = load_json_file(
        root / "test-design" / "testcases_v1.json",
        []
    )

    testcases_v2 = load_json_file(
        root / "test-design" / "testcases_v2.json",
        {}
    )

    generator_comparison = load_json_file(
        root / "test-design" / "generator_comparison.json",
        {}
    )

    testcases_v2_reviewed = load_json_file(
        root / "test-design" / "testcases_v2_reviewed.json",
        {}
    )

    test_quality_report = load_json_file(
        root / "test-design" / "test_quality_report.json",
        {}
    )

    correction_history = load_json_file(
        root / "test-design" / "correction_history.json",
        {}
    )

    traceability = load_json_file(
        root / "traceability.json",
        {}
    )

    export_gate_status = load_json_file(
        root / "test-design" / "export_gate_status.json",
        {}
    )

    clarification_questions_v2 = load_json_file(
        root / "analysis" / "clarification_questions_v2.json",
        {}
    )

    selected_references = load_json_file(
        root / "knowledge" / "selected_references.json",
        []
    )

    rejected_references = load_json_file(
        root / "knowledge" / "rejected_references.json",
        []
    )

    knowledge_conflicts = load_json_file(
        root / "knowledge" / "conflicts.json",
        []
    )

    requirement_summary = load_json_file(
        root / "analysis" / "requirement_summary.json",
        {}
    )
    
    test_scope = load_json_file(
        root / "analysis" / "test_scope.json",
        {}
    )    

    scenarios = load_json_file(
        root / "analysis" / "scenarios.json",
        []
    )

    testcases = load_json_file(
        root / "testcases" / "improved_testcases.json",
        []
    )

    if not testcases:
        testcases = load_json_file(
            root / "testcases" / "testcases.json",
            []
        )

    coverage_review = load_json_file(
        root / "review" / "coverage_review.json",
        {}
    )

    final_coverage_review = load_json_file(
        root / "review" / "final_coverage_review.json",
        {}
    )

    session = load_json_file(
        root / "review" / "review_session.json",
        {
            "improve_iterations": 0,
            "max_iterations": 3,
            "accepted": False
        }
    )
    
    improvement_history = load_improvement_history(ticket_id)

    return {
        "ticket_id": ticket_id,
        "analysis": analysis,
        "structured_analysis": structured_analysis,
        "quality_report": quality_report,
        "enriched_analysis": enriched_analysis,
        "enrichment_diff": enrichment_diff,
        "enrichment_approval": enrichment_approval,
        "coverage_model": coverage_model,
        "coverage_analysis": coverage_analysis,
        "testcases_v1": testcases_v1,
        "testcases_v2": testcases_v2,
        "generator_comparison": generator_comparison,
        "testcases_v2_reviewed": testcases_v2_reviewed,
        "test_quality_report": test_quality_report,
        "correction_history": correction_history,
        "traceability": traceability,
        "export_gate_status": export_gate_status,
        "clarification_questions_v2": clarification_questions_v2,
        "selected_references": selected_references,
        "rejected_references": rejected_references,
        "knowledge_conflicts": knowledge_conflicts,
        "requirement_qa": requirement_qa,
        "clarifications": clarifications,
        "clarification_answers": clarification_answers,
        "requirement_summary": requirement_summary,
        "review_comments": review_comments,
        "test_scope": test_scope,
        "scenarios": scenarios,
        "testcases": testcases,
        "coverage_review": coverage_review,
        "final_coverage_review": final_coverage_review,
        "improvement_history": improvement_history,
        "session": session
    }
