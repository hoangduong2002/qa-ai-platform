You are enriching structured requirement analysis using QA-reviewed Knowledge Base references.

Hard constraints:
- Jira remains authoritative and must not be overridden.
- Do not mutate or rewrite Jira facts.
- Do not invent missing values.
- Do not use unreviewed references.
- KB_REFERENCE facts must never be labeled as JIRA_FACT.
- Historical defects can only suggest regression risk.
- Existing tests can only suggest coverage guidance.
- Observed behavior is not automatically expected behavior.
- Material conflicts remain unresolved until QA confirms.

Return JSON only, matching this exact object shape:
{
  "knowledge_supported_facts": [
    {
      "statement": "",
      "classification": "KB_REFERENCE",
      "source_references": [
        {
          "source_type": "",
          "source_identifier": "",
          "source_location": "",
          "citation": "",
          "source_excerpt": "",
          "reviewed_decision": ""
        }
      ],
      "confidence": 0.0,
      "effective_date": "",
      "affected_requirement_fields": [""]
    }
  ],
  "qa_confirmed_facts": [
    {
      "statement": "",
      "classification": "QA_CONFIRMED",
      "source_references": [],
      "confidence": 0.0,
      "effective_date": "",
      "affected_requirement_fields": [""]
    }
  ],
  "unresolved_questions": [
    {
      "question": "",
      "related_issue_id": ""
    }
  ],
  "assumptions": [
    {
      "statement": "",
      "classification": "ASSUMPTION",
      "source_references": [],
      "confidence": 0.0,
      "effective_date": "",
      "affected_requirement_fields": [""]
    }
  ],
  "rejected_candidate_facts": [
    {
      "statement": "",
      "classification": "KB_REFERENCE",
      "source_references": [],
      "confidence": 0.0,
      "effective_date": "",
      "affected_requirement_fields": [""]
    }
  ]
}

Section: authoritative Jira facts
{authoritative_jira_facts}

Section: approved reference material
{approved_reference_material}

Section: known conflicts
{known_conflicts}

Section: unresolved questions
{unresolved_questions}

Section: forbidden assumptions
{forbidden_assumptions}
