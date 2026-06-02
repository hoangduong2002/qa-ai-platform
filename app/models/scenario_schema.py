from typing import TypedDict


class TestScenario(TypedDict):

    scenario_id: str

    title: str

    category: str

    description: str

    related_requirements: list[str]