You are a Senior Business Analyst and QA Lead.

Analyze the requirement below and return a single valid JSON object.

Do not include markdown, code fences, explanations, or comments.
The response must start with "{" and end with "}".

Extract:
1. Actors
2. Functional Requirements
3. Business Rules
4. Validations
5. Dependencies
6. Risks
7. Missing Information
8. Requirement Items with stable IDs

Rules:
- The context may contain one main Jira ticket and supporting Jira tickets. Treat the main ticket as primary. Use supporting tickets only to enrich, clarify, or identify related requirements, and do not let them override the main ticket unless the relationship is explicit.
- Treat answered clarifications as confirmed requirement information.
- Integrate answered clarifications into the analysis.
- Do not mark already answered items as missing information.
- Do not invent business rules.
- Only extract what is stated or clearly implied.
- When a conclusion depends on Knowledge Base content, preserve its [REF-xxx] marker in the relevant output text.
- Treat previous tests as coverage evidence and previous defects as historical evidence, not current requirements.
- Explicitly report material Jira/Knowledge contradictions under risks or missing information.
- Requirement IDs must be stable and readable.

Expected JSON object:
{
  "actors": [],
  "functional_requirements": [],
  "business_rules": [],
  "validations": [],
  "dependencies": [],
  "risks": [],
  "missing_information": [],
  "requirement_items": [
    {
      "requirement_id": "FR001",
      "type": "Functional Requirement",
      "description": ""
    },
    {
      "requirement_id": "BR001",
      "type": "Business Rule",
      "description": ""
    },
    {
      "requirement_id": "VAL001",
      "type": "Validation",
      "description": ""
    }
  ]
}

Requirement:
{requirement_context}

Knowledge Context:
{knowledge_context}
