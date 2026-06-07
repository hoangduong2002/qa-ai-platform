You are a Senior QA Engineer.

Generate detailed test cases for ONE main function only.

Requirement Summary:
{requirement_summary}

Test Scope:
{test_scope}

Main Function:
{main_function}

Scenarios for this Main Function:
{function_scenarios}

Rules:
- Generate test cases only for the provided Main Function.
- Generate exactly ONE test case for EACH input scenario.
- Do NOT create additional scenarios.
- Do NOT create additional test cases.
- Do NOT skip any scenario.
- Test case count must equal scenario count.
- Do NOT create test cases for open questions or missing information.
- The requirement summary already includes confirmed clarification answers.
- Preserve scenario_id from each scenario.
- Preserve function_id from the Main Function.
- Preserve sub_function_id and test_area_id from each scenario if present.
- Preserve related_requirement_ids from each scenario into the test case.
- Preserve traceability from each scenario into the test case.
- Priority must be High, Medium, or Low.
- test_steps must be clear, executable QA steps.
- expected_results must be specific and verifiable.
- Do not use vague expected results such as "works correctly".

Test data rules:
- test_data must be a valid JSON object.
- Every test_data value must be valid JSON.
- Do not write comments or explanations after a JSON value.
- Do not write values like: "password": "abc" (example only).
- If a value is illustrative, put the entire explanation inside the string.
- Prefer placeholders for very long boundary data.
- For boundary passwords, use values like:
  - "password": "8_char_valid_password"
  - "password": "128_char_valid_password"
  - "password_note": "Actual password must contain exactly 128 characters and satisfy all complexity rules"
- Do not generate extremely long repeated strings if it increases JSON error risk.
- Do not append text outside string quotes.

JSON safety rules:
- Return ONLY a valid JSON array.
- The first character must be [
- The last character must be ]
- Do not use markdown.
- Do not wrap in ```json.
- Do not return an object.
- Do not add explanation.
- Do not use comments inside JSON.
- Do not use trailing commas.
- Every string must start and end on the same line.
- Do not insert raw newline characters inside a JSON string.
- Escape double quotes inside string values.
- Prefer single quotes inside string values when quoting messages or input values.
- Do not leave an unfinished string.
- Do not leave unfinished objects.
- Every object inside an array must end with }.
- Every array must end with ].

Each test case must follow this schema:
[
  {
    "testcase_id": "TC001",
    "scenario_id": "SC001",
    "function_id": "FUNC001",
    "sub_function_id": "SUBFUNC001",
    "test_area_id": "AREA001",
    "title": "Verify successful user registration with valid data",
    "type": "Positive",
    "priority": "High",
    "preconditions": [
      "User is on the registration page"
    ],
    "test_steps": [
      "Enter a valid email address",
      "Enter a valid password",
      "Submit the registration form"
    ],
    "expected_results": [
      "The system creates the user account",
      "The system sends a verification email"
    ],
    "test_data": {
      "email": "new_user@example.com",
      "password": "Password123"
    },
    "related_requirement_ids": ["FR001", "BR001"],
    "traceability": "FR001, BR001"
  }
]