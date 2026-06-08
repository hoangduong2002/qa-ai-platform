def _to_text(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "\n".join(str(item) for item in value)

    if isinstance(value, dict):
        return str(value)

    return str(value)


def _get_score(review: dict):
    return (
        review.get("coverage_score")
        or review.get("score")
        or review.get("structure_score")
        or "N/A"
    )


def _get_approved(review: dict):
    return (
        review.get("approved_by_ai")
        or review.get("approved")
        or False
    )


def _extract_issues(review: dict) -> list:
    if not isinstance(review, dict):
        return []

    for key in [
        "issues",
        "structure_issues",
        "gaps",
        "missing_areas",
        "recommendations",
    ]:
        value = review.get(key)

        if isinstance(value, list):
            return value

    return []


def _get_issue_severity(issue: dict) -> str:
    return (
        issue.get("severity")
        or issue.get("priority")
        or issue.get("impact")
        or "Medium"
    )


def _get_issue_title(issue: dict) -> str:
    return (
        issue.get("title")
        or issue.get("issue")
        or issue.get("gap")
        or issue.get("description")
        or issue.get("recommendation")
        or "Structure review item"
    )


def _get_issue_recommendation(issue: dict) -> str:
    return (
        issue.get("recommendation")
        or issue.get("suggestion")
        or issue.get("action")
        or issue.get("description")
        or ""
    )


def _build_suggested_comment(issue: dict) -> str:
    recommendation = _get_issue_recommendation(issue)
    title = _get_issue_title(issue)

    if recommendation:
        return recommendation

    return f"Please improve the test case structure for: {title}"


def render_structure_review_chat_summary(
    ticket_id: str,
    version: str,
    review: dict,
    max_items: int = 10,
) -> str:
    score = _get_score(review)
    approved = _get_approved(review)
    issues = _extract_issues(review)

    message = (
        f"✅ Structure AI review completed for {ticket_id}\n\n"
        f"Version: {version}\n"
        f"AI Coverage Score: {score}\n"
        f"AI Approved: {approved}\n\n"
    )

    if not issues:
        message += (
            "No major structure issues were found.\n\n"
            "You can click Approve if the structure looks acceptable, "
            "or click Comment if you still want to adjust it."
        )
        return message

    message += "Top Issues / Recommendations:\n\n"

    for index, issue in enumerate(issues[:max_items], start=1):
        if not isinstance(issue, dict):
            message += f"{index}. {_to_text(issue)}\n\n"
            continue

        severity = _get_issue_severity(issue)
        title = _get_issue_title(issue)
        suggested_comment = _build_suggested_comment(issue)

        message += (
            f"{index}. [{severity}] {title}\n"
            f"Suggested comment:\n"
            f"{suggested_comment}\n\n"
        )

    if len(issues) > max_items:
        message += (
            f"...and {len(issues) - max_items} more item(s). "
            f"Please check the Excel file for full details.\n\n"
        )

    message += (
        "You can copy one or more suggested comments and click Comment "
        "to improve the structure."
    )

    return message