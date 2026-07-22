from __future__ import annotations

from evaluation.metrics.deterministic import forbidden_assumption_count
from evaluation.metrics.semantic_matcher import ConservativeSemanticMatcher


def test_forbidden_assumption_count_matches_corpus() -> None:
    count = forbidden_assumption_count(
        forbidden_assumptions=["guest checkout is always enabled"],
        text_corpus=["The flow assumes guest checkout is always enabled for all users."],
        matcher=ConservativeSemanticMatcher(),
    )

    assert count == 1
