MAX_TELEGRAM_MESSAGE_LENGTH = 3500


def _to_text(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "\n".join(str(item) for item in value)

    return str(value)


def _get_review_items(review: dict) -> list:
    items = []

    for key in [
        "missing_scenarios",
        "weak_testcases",
        "traceability_issues",
        "execution_readiness_issues",
        "recommendations",
    ]:
        value = review.get(key, [])

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item = dict(item)
                    item["_source"] = key
                    items.append(item)
                else:
                    items.append(
                        {
                            "_source": key,
                            "issue": str(item),
                        }
                    )

    return items


def render_testcase_review_chat_summary(
    ticket_id: str,
    review: dict,
    max_items: int = 10,
) -> str:
    score = review.get("coverage_score", "N/A")
    approved = review.get("approved_by_ai", False)

    message = (
        f"✅ AI test case review completed for {ticket_id}\n\n"
        f"Coverage Score: {score}\n"
        f"Approved by AI: {approved}\n\n"
    )

    score_breakdowns = review.get("score_breakdowns") or []

    if score_breakdowns:
        message += "Score Breakdown:\n"

        for item in score_breakdowns[:5]:
            function_id = item.get("function_id", "")
            function_name = item.get("function_name", "")
            scenario_score = item.get("scenario_coverage_score", "")
            traceability_score = item.get("traceability_score", "")
            design_score = item.get("test_design_score", "")
            readiness_score = item.get("execution_readiness_score", "")

            message += (
                f"- {function_id} {function_name}: "
                f"Scenario {scenario_score}/40, "
                f"Traceability {traceability_score}/20, "
                f"Design {design_score}/20, "
                f"Readiness {readiness_score}/20\n"
            )

        message += "\n"

    items = _get_review_items(review)

    if not items:
        message += (
            "No major review issues were found.\n\n"
            "You can click Accept if the test cases are acceptable, "
            "or click Comment if you still want to improve them."
        )
    else:
        message += "Top Issues / Recommendations:\n\n"

        for index, item in enumerate(items[:max_items], start=1):
            source = item.get("_source", "")
            testcase_id = (
                item.get("testcase_id")
                or item.get("item_id")
                or ""
            )
            scenario_id = item.get("scenario_id", "")
            issue = (
                item.get("issue")
                or item.get("reason")
                or item.get("recommendation")
                or item.get("summary")
                or ""
            )
            recommendation = item.get("recommendation", "")

            target = testcase_id or scenario_id or source

            message += (
                f"{index}. [{source}] {target}\n"
                f"Issue: {issue}\n"
            )

            if recommendation:
                message += f"Suggested comment:\n{recommendation}\n"

            message += "\n"

        if len(items) > max_items:
            message += (
                f"...and {len(items) - max_items} more item(s). "
                f"Please check the Excel file for full details.\n\n"
            )

        message += (
            "You can copy one or more suggested comments and click Comment "
            "to improve the test cases."
        )

    if len(message) > MAX_TELEGRAM_MESSAGE_LENGTH:
        message = (
            message[:MAX_TELEGRAM_MESSAGE_LENGTH]
            + "\n\n... Message truncated. Please check the Excel file for full details."
        )

    return message