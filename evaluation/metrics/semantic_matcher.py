from __future__ import annotations

import re


class SemanticMatcher:
    """Abstraction for semantic matching with conservative deterministic fallback."""

    def count_matches(self, expected_items: list[str], candidate_items: list[str]) -> int:
        raise NotImplementedError


class ConservativeSemanticMatcher(SemanticMatcher):
    def _normalize(self, value: str) -> str:
        value = (value or "").lower()
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _matches(self, expected: str, candidate: str) -> bool:
        expected_norm = self._normalize(expected)
        candidate_norm = self._normalize(candidate)

        if not expected_norm or not candidate_norm:
            return False

        return expected_norm in candidate_norm or candidate_norm in expected_norm

    def count_matches(self, expected_items: list[str], candidate_items: list[str]) -> int:
        matched = 0

        for expected in expected_items:
            if any(self._matches(expected, candidate) for candidate in candidate_items):
                matched += 1

        return matched
