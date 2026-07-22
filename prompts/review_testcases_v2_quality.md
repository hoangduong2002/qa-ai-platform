Review attempt: {review_attempt} of 2.

Independently review the generated V2 test cases. The generator's presence of a citation is not proof that the cited source supports the claim. Do not approve an unsupported expected result.

Review all of these categories:
- Groundedness: unsupported expected result; invented amount, status, message, or calculation; KB contradiction with Jira; missing source reference.
- Requirement coverage: uncovered acceptance criterion, business rule, blocking condition, or clarification.
- Coverage quality: missing positive, negative, boundary, permission, state-transition, integration-failure, or regression coverage.
- Test-case quality: vague title, invalid precondition, multiple actions, unobservable expected result, missing data, contradictory steps, duplicate/near duplicate, out-of-scope, or non-executable case.

Rules:
- Treat Jira as authoritative over Knowledge Base content.
- Only ACCEPTED Knowledge Base references may support expected behavior.
- Historical defects do not define correct behavior without independent confirmation.
- Preserve every deterministic finding unless the supplied evidence conclusively disproves it.
- Each issue must be actionable, source-grounded where applicable, and use INFO, WARNING, or BLOCKER.
- Set blocks_export=true for every BLOCKER.
- Remaining unsupported behavior must make review_status NEEDS_QA_REVIEW.
- Return JSON only.

Reviewer inputs:
{review_inputs}

Generated test cases:
{generated_testcases}

Deterministic findings:
{deterministic_findings}

Output schema:
{review_schema}
