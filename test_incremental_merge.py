"""Offline incremental testcase merge test.

Usage:
    python test_incremental_merge.py

This script uses local fixtures only. It verifies that changed test cases are
replaced, removed-source cases become DeprecatedCandidate, and unaffected cases
remain unchanged.
"""
from __future__ import annotations

from app.services.incremental_generation_service import merge_testcases
from _incremental_test_utils import load_fixture, print_summary


def main() -> int:
    old_testcases = load_fixture("old_testcases.json")
    new_testcases = load_fixture("new_testcases_impacted.json")

    regeneration_plan = {
        "ticket_id": "INC-001",
        "plan_version": 1,
        "source_snapshot_version": 2,
        "change_report_version": 1,
        "impact_confidence": "HIGH",
        "can_partial_regenerate": True,
        "impacted_requirement_ids": ["REQ-001", "REQ-002", "REQ-003", "REQ-004"],
        "impacted_scenario_ids": ["SC-001", "SC-002", "SC-004"],
        "impacted_testcase_ids": ["TC-001", "TC-003"],
        "deprecated_candidate_testcase_ids": ["TC-004"],
        "deprecated_candidate_scenario_ids": [],
        "safety": {
            "overall_status": "PARTIAL_REGENERATE_ALLOWED",
            "safety_reasons": [],
        },
    }

    merged = merge_testcases(old_testcases, new_testcases, regeneration_plan)
    by_id = {
        item["testcase_id"]: item
        for item in merged
        if isinstance(item, dict) and item.get("testcase_id")
    }

    checks = []

    def check_statuses() -> None:
        assert by_id["TC-001"]["change_status"] == "Replaced"
        assert by_id["TC-002"]["change_status"] == "Unchanged"
        assert by_id["TC-003"]["change_status"] == "Replaced"
        assert by_id["TC-004"]["change_status"] == "DeprecatedCandidate"

    checks.append(("status assignment", check_statuses))

    def check_new_testcases() -> None:
        assert by_id["TC-101"]["previous_testcase_id"] == "TC-001"
        assert by_id["TC-102"]["change_status"] == "New"
        assert by_id["TC-103"]["previous_testcase_id"] == "TC-003"
        assert by_id["TC-102"]["related_scenario_id"] == "SC-002"
        assert by_id["TC-103"]["related_scenario_id"] == "SC-004"

    checks.append(("new testcase merge", check_new_testcases))

    def check_preservation() -> None:
        assert by_id["TC-002"]["title"] == "Verify unaffected baseline flow"
        assert len(merged) == 7

    checks.append(("preserve unaffected cases", check_preservation))

    passed = 0
    failed = 0

    for label, check in checks:
        try:
            check()
            passed += 1
            print(f"PASS {label}")
        except Exception as error:
            failed += 1
            print(f"FAIL {label}: {error}")

    print_summary("Incremental merge", passed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())