def normalize_node_name(node_name: str) -> str:
    node_name = node_name or "unknown"

    known_prefixes = [
        "generate_scenarios",
        "generate_testcases",
        "improve_testcases",
        "final_coverage_review",
        "coverage_review",
        "generate_test_scope",
        "generate_test_case_structure",
        "review_test_case_structure",
        "improve_test_case_structure",
        "analyze_requirement",
        "generate_clarifications",
        "generate_requirement_summary",
        "scenario_coverage_review",
        "improve_scenarios",
    ]

    for prefix in known_prefixes:
        if node_name == prefix or node_name.startswith(f"{prefix}_"):
            return prefix

    return node_name