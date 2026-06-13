"""Offline Jira delta comparison test.

Usage:
    python test_jira_delta_compare.py

This script uses local JSON fixtures only. It validates that compare_jira_snapshots
flags comment, subtask, attachment, and Figma screen changes without touching
external services.
"""
from __future__ import annotations

from app.services.jira_delta_service import compare_jira_snapshots
from _incremental_test_utils import assert_change_types, load_fixture, print_summary


TICKET_ID = "INC-001"


def main() -> int:
    old_snapshot = load_fixture("jira_snapshot_old.json")
    comment_added_snapshot = load_fixture("jira_snapshot_new_comment_added.json")
    subtask_added_snapshot = load_fixture("jira_snapshot_new_subtask_added.json")
    figma_changed_snapshot = load_fixture("jira_snapshot_figma_screen_changed.json")

    checks = []

    def check_comment_changes() -> None:
        changes = compare_jira_snapshots(old_snapshot, comment_added_snapshot)
        assert_change_types(
            changes,
            {"comment_added", "comment_modified", "attachment_added"},
        )

    checks.append(("comment/add/modify detection", check_comment_changes))

    def check_subtask_change() -> None:
        changes = compare_jira_snapshots(old_snapshot, subtask_added_snapshot)
        assert_change_types(changes, {"subtask_added"})

    checks.append(("subtask added detection", check_subtask_change))

    def check_figma_changes() -> None:
        changes = compare_jira_snapshots(old_snapshot, figma_changed_snapshot)
        assert_change_types(changes, {"figma_screen_added", "figma_screen_image_changed"})

    checks.append(("figma screen detection", check_figma_changes))

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

    print_summary("Jira delta compare", passed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())