"""Offline snapshot smoke test for Jira incremental sync fixtures.

Usage:
    python test_jira_delta_snapshot.py

This script does not call Jira, Figma, DeepSeek, or Ollama. It validates the
fixture snapshot structure and verifies save/load round-trip behavior with a
temporary requirements root.
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import app.services.jira_delta_service as jira_delta_service
from _incremental_test_utils import load_fixture, print_summary


TICKET_ID = "INC-001"


def main() -> int:
    snapshot = load_fixture("jira_snapshot_old.json")

    checks = []

    def check_fixture_shape() -> None:
        assert snapshot["metadata"]["ticket_id"] == TICKET_ID
        assert snapshot["field_hashes"]["summary_hash"]
        assert len(snapshot.get("comments_inventory", [])) == 1
        assert len(snapshot.get("subtasks_inventory", [])) == 1
        assert len(snapshot.get("attachments_inventory", [])) == 1
        assert len(snapshot.get("figma_screen_inventory", [])) == 1

    checks.append(("fixture shape", check_fixture_shape))

    def check_save_load_roundtrip() -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_root = jira_delta_service.REQUIREMENTS_ROOT
            try:
                jira_delta_service.REQUIREMENTS_ROOT = Path(tmp_dir) / "requirements"
                payload = copy.deepcopy(snapshot)
                save_result = jira_delta_service.save_jira_snapshot(TICKET_ID, payload)
                loaded = jira_delta_service.load_latest_jira_snapshot(TICKET_ID)

                assert save_result["ticket_id"] == TICKET_ID
                assert save_result["snapshot_version"] == 1
                assert loaded == payload
            finally:
                jira_delta_service.REQUIREMENTS_ROOT = previous_root

    checks.append(("save/load round-trip", check_save_load_roundtrip))

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

    print_summary("Jira snapshot smoke test", passed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())