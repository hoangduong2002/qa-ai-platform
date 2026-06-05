from pathlib import Path


from pathlib import Path


def get_requirement_status(ticket_id: str):

    root = Path("requirements") / ticket_id

    analysis_dir = root / "analysis"
    testcases_dir = root / "testcases"
    review_dir = root / "review"

    if (testcases_dir / "improved_testcases.json").exists():
        return "🟢", "Improved Test Cases Generated"

    if (testcases_dir / "testcases.json").exists():
        return "🟢", "Test Cases Generated"

    if (analysis_dir / "test_scope.json").exists():
        return "🔵", "Test Scope Ready"

    if (analysis_dir / "requirement_summary.json").exists():
        return "🔵", "Requirement Intelligence Completed"

    if (
        (analysis_dir / "clarifications.json").exists()
        and not (analysis_dir / "clarification_answers.json").exists()
    ):
        return "🟡", "Awaiting Clarification Answers"

    if (
        (analysis_dir / "clarifications.json").exists()
        and (analysis_dir / "clarification_answers.json").exists()
    ):
        return "🟣", "Clarifications Answered"

    if (analysis_dir / "requirement_analysis.json").exists():
        return "🟠", "Requirement Analyzed"

    return "⚪", "Created"