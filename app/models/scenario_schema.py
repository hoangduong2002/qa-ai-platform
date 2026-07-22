from typing import NotRequired, TypedDict


class TestScenario(TypedDict):

    scenario_id: str

    title: str

    category: str

    description: str

    related_requirements: list[str]

    coverage_ids: NotRequired[list[str]]
