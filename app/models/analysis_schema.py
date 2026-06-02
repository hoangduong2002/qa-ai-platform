from typing import TypedDict


class RequirementAnalysis(TypedDict):

    actors: list[str]

    functional_requirements: list[str]

    business_rules: list[str]

    validations: list[str]

    dependencies: list[str]

    risks: list[str]

    missing_information: list[str]