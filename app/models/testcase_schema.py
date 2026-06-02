from typing import TypedDict


class TestCase(TypedDict):

    testcase_id: str

    scenario_id: str

    related_requirements: list[str]

    title: str

    priority: str

    preconditions: list[str]

    test_steps: list[str]

    expected_results: list[str]