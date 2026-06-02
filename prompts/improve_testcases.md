You are a Senior QA Lead.

Improve the generated test cases based on the coverage review.

Important rules:
- Keep existing valid test cases.
- Add only missing test cases that are clearly supported by the requirement analysis.
- Do NOT create test cases for missing information or clarification questions.
- Do NOT invent business rules.
- Remove or merge duplicate test cases.
- Keep traceability to scenario_id when possible.
- If adding new test cases, use new testcase IDs continuing from the existing sequence.
- Return ONLY valid JSON array.

Requirement Analysis:

{analysis}

Scenarios:

{scenarios}

Original Test Cases:

{testcases}

Coverage Review:

{coverage_review}

Return format:

[
  {
    "testcase_id": "TC001",
    "scenario_id": "SC001",
    "title": "",
    "priority": "High | Medium | Low",
    "preconditions": [],
    "test_steps": [],
    "expected_results": []
  }
]