"""Offline impact-mapping test for Jira incremental sync.

Usage:
    python test_impact_mapping.py

This script merges local change fixtures into one compare report, runs
build_regeneration_plan, and verifies requirement/testcase mapping without any
LLM, Jira, or Figma calls.
"""
from __future__ import annotations

from collections import Counter

from app.services.impact_mapping_service import (
    SAFETY_PARTIAL_ALLOWED,
    build_regeneration_plan,
    load_latest_regeneration_plan,
)
from app.services.jira_delta_service import compare_jira_snapshots
from _incremental_test_utils import load_fixture, print_summary


TICKET_ID = "INC-001"


def _combined_change_report() -> dict:
    old_snapshot = load_fixture("jira_snapshot_old.json")
    comment_added_snapshot = load_fixture("jira_snapshot_new_comment_added.json")
    subtask_added_snapshot = load_fixture("jira_snapshot_new_subtask_added.json")
    figma_changed_snapshot = load_fixture("jira_snapshot_figma_screen_changed.json")

    changes = []
    changes.extend(compare_jira_snapshots(old_snapshot, comment_added_snapshot))
    changes.extend(compare_jira_snapshots(old_snapshot, subtask_added_snapshot))
    changes.extend(compare_jira_snapshots(old_snapshot, figma_changed_snapshot))

    counts = Counter(item["change_type"] for item in changes)
    return {
        "ticket_id": TICKET_ID,
        "report_version": 1,
        "new_snapshot_version": 2,
        "changes": changes,
        "change_count": len(changes),
        "change_counts": dict(counts),
    }


def main() -> int:
    change_report = _combined_change_report()
    traceability = load_fixture("source_traceability_matrix.json")
    scenarios = [
        {
            "scenario_id": "SC-001",
            "title": "Comment workflow",
            "related_requirement_ids": ["REQ-001"],
            "source_refs": ["comment:c1", "comment:c2"],
        },
        {
            "scenario_id": "SC-002",
            "title": "Subtask workflow",
            "related_requirement_ids": ["REQ-002"],
            "source_refs": ["subtask:sub-2"],
        },
        {
            "scenario_id": "SC-003",
            "title": "Attachment workflow",
            "related_requirement_ids": ["REQ-003"],
            "source_refs": ["attachment:att-2"],
        },
        {
            "scenario_id": "SC-004",
            "title": "Figma screen workflow",
            "related_requirement_ids": ["REQ-004"],
            "source_refs": [
                "figma_screen:FIG-100:Page-A:Node-1",
                "figma_screen:FIG-100:Page-A:Node-2",
            ],
        },
    ]
    old_testcases = load_fixture("old_testcases.json")

    checks = []

    def check_requirements_and_testcases() -> None:
        plan = build_regeneration_plan(
            ticket_id=TICKET_ID,
            change_report=change_report,
            traceability=traceability,
            scenarios=scenarios,
            testcases=old_testcases,
        )

        assert plan["impact_confidence"] == "HIGH"
        assert plan["can_partial_regenerate"] is True
        assert plan["safety"]["overall_status"] == SAFETY_PARTIAL_ALLOWED
        assert set(plan["impacted_requirement_ids"]) == {
            "REQ-001",
            "REQ-002",
            "REQ-003",
            "REQ-004",
        }
        assert set(plan["impacted_testcase_ids"]) == {"TC-001", "TC-003"}
        assert set(plan["unchanged_testcase_ids"]) == {"TC-002", "TC-004"}
        assert plan["safety"]["missing_traceability"] is False

        latest_plan = load_latest_regeneration_plan(TICKET_ID)
        assert latest_plan == {}

    checks.append(("impact mapping and safety", check_requirements_and_testcases))

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

    print_summary("Impact mapping", passed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())