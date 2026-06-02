from typing import TypedDict


class QAState(TypedDict):

    ticket_id: str

    requirement_context: str

    analysis: dict
    
    clarifications: dict
    
    test_scope: dict

    scenarios: list

    testcases: list
    
    coverage_review: dict
    
    improved_testcases: list
    
    final_coverage_review: dict