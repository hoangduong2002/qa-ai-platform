from __future__ import annotations

import os

from app.services.knowledge_reference_review.models import AuthorityPolicy, SourceAuthority


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def reference_review_required() -> bool:
    return _env_bool("KNOWLEDGE_REFERENCE_REVIEW_REQUIRED", True)


def llm_conflict_assist_enabled() -> bool:
    return _env_bool("KNOWLEDGE_REFERENCE_REVIEW_LLM_CONFLICT_ASSIST", False)


def authorized_reviewers() -> list[str]:
    raw = os.getenv("KNOWLEDGE_REFERENCE_REVIEWER_IDS", "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def default_authority_policy() -> AuthorityPolicy:
    # Default order from Phase 5 policy.
    return AuthorityPolicy(
        ordered_authorities=[
            SourceAuthority.CURRENT_JIRA_TICKET,
            SourceAuthority.CONFIRMED_JIRA_COMMENTS_OR_CLARIFICATIONS,
            SourceAuthority.OFFICIAL_ACTIVE_BUSINESS_RULES,
            SourceAuthority.API_AND_INTEGRATION_SPECIFICATIONS,
            SourceAuthority.EXISTING_TEST_CASES,
            SourceAuthority.HISTORICAL_DEFECTS,
            SourceAuthority.OBSERVED_CURRENT_BEHAVIOR,
        ]
    )
