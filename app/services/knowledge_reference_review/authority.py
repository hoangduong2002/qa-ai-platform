from __future__ import annotations

from app.services.knowledge_reference_review.models import AuthorityPolicy, SourceAuthority


SOURCE_TYPE_TO_AUTHORITY = {
    "JIRA_TICKET": SourceAuthority.CURRENT_JIRA_TICKET,
    "JIRA_COMMENT": SourceAuthority.CONFIRMED_JIRA_COMMENTS_OR_CLARIFICATIONS,
    "JIRA_CLARIFICATION": SourceAuthority.CONFIRMED_JIRA_COMMENTS_OR_CLARIFICATIONS,
    "BUSINESS_RULE": SourceAuthority.OFFICIAL_ACTIVE_BUSINESS_RULES,
    "API_SPEC": SourceAuthority.API_AND_INTEGRATION_SPECIFICATIONS,
    "INTEGRATION_SPEC": SourceAuthority.API_AND_INTEGRATION_SPECIFICATIONS,
    "TEST_CASE": SourceAuthority.EXISTING_TEST_CASES,
    "DEFECT": SourceAuthority.HISTORICAL_DEFECTS,
    "OBSERVED_BEHAVIOR": SourceAuthority.OBSERVED_CURRENT_BEHAVIOR,
}


def source_authority_for_source_type(source_type: str) -> SourceAuthority:
    return SOURCE_TYPE_TO_AUTHORITY.get((source_type or "").strip().upper(), SourceAuthority.UNKNOWN)


def is_jira_more_authoritative_than(source_type: str, policy: AuthorityPolicy) -> bool:
    source_authority = source_authority_for_source_type(source_type)

    jira_rank = _rank(SourceAuthority.CURRENT_JIRA_TICKET, policy)
    source_rank = _rank(source_authority, policy)

    return jira_rank <= source_rank


def _rank(authority: SourceAuthority, policy: AuthorityPolicy) -> int:
    for index, item in enumerate(policy.ordered_authorities):
        if item == authority:
            return index

    return len(policy.ordered_authorities) + 1
