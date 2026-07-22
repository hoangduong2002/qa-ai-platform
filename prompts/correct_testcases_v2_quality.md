Correct only the test cases affected by the supplied auto-correctable issues.

Rules:
- Return the complete corrected test-case set and an exact change log.
- Do not change an unaffected case in any way.
- Preserve stable test_case_id values wherever possible.
- Do not add amounts, statuses, messages, calculations, test data, preconditions, or expected behavior unless an authoritative/approved source explicitly supports them.
- Do not convert an unsupported fact into a confident expected result.
- Preserve scope exclusions and traceability.
- If evidence is insufficient, retain the case as an explicit assumption or unresolved question instead of inventing a correction.
- Return JSON only.

Source inputs:
{review_inputs}

Current test cases:
{generated_testcases}

Issues allowed to be corrected:
{correction_issues}

Output schema:
{correction_schema}
