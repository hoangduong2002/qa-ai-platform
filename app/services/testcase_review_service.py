from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.test_structure_store import load_approved_test_case_structure
from graph.nodes.review_coverage import coverage_review


def run_testcase_ai_review(ticket_id: str) -> dict:
    artifacts = load_ticket_artifacts(ticket_id)

    approved_structure = (
        artifacts.get("approved_test_case_structure")
        or artifacts.get("test_case_structure")
        or artifacts.get("approved_structure")
        or load_approved_test_case_structure(ticket_id)
        or {}
    )

    if not approved_structure:
        raise ValueError(
            "approved_test_case_structure is required for AI test case review. "
            "Please approve the test case structure first."
        )

    state = {
        "ticket_id": ticket_id,
        "analysis": artifacts.get("analysis", {}),
        "requirement_summary": artifacts.get("requirement_summary", {}),
        "test_scope": artifacts.get("test_scope", {}),
        "approved_test_case_structure": approved_structure,
        "scenarios": artifacts.get("scenarios", []),
        "testcases": (
            artifacts.get("improved_testcases")
            or artifacts.get("testcases")
            or []
        ),
    }

    return coverage_review(state)