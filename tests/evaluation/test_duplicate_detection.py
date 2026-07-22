from __future__ import annotations

from evaluation.metrics.deterministic import duplicate_testcase_rate


def test_duplicate_testcase_rate_detects_duplicates() -> None:
    testcases = [
        {
            "test_case": "A",
            "precondition": "P",
            "steps": "S",
            "expected_result": "E",
        },
        {
            "test_case": "A",
            "precondition": "P",
            "steps": "S",
            "expected_result": "E",
        },
    ]

    duplicates, rate = duplicate_testcase_rate(testcases)

    assert duplicates == 1
    assert rate == 0.5
