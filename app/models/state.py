from typing import TypedDict, NotRequired


class QAState(TypedDict):
    ticket_id: str

    requirement_context: NotRequired[str]
    requirement_context_metadata: NotRequired[dict]

    analysis: NotRequired[dict]
    requirement_qa: NotRequired[dict]
    clarifications: NotRequired[dict]
    clarification_answers: NotRequired[dict]
    requirement_summary: NotRequired[dict]
    test_scope: NotRequired[dict]

    generation_mode: NotRequired[str]
    ai_mode: NotRequired[str]
    source_channel: NotRequired[str]
    approved_test_case_structure: NotRequired[dict]

    scenarios: NotRequired[list]
    testcases: NotRequired[list]

    function_testcase_results: NotRequired[list]
    function_generation_manifest_file: NotRequired[str]

    coverage_review: NotRequired[dict]
    function_coverage_results: NotRequired[list]
    function_coverage_manifest_file: NotRequired[str]

    improved_testcases: NotRequired[list]
    function_improve_results: NotRequired[list]
    function_improve_manifest_file: NotRequired[str]

    final_coverage_review: NotRequired[dict]
    function_final_review_results: NotRequired[list]
    function_final_review_manifest_file: NotRequired[str]

    excel_file: NotRequired[str]
