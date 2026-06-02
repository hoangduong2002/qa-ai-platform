from typing import TypedDict


class TestCaseState(TypedDict):

    ticket_id: str

    requirement_context: str

    analysis: dict

    scenarios: list[dict]

    testcases: list[dict]

    coverage_review: dict