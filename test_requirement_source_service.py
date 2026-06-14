"""Offline smoke test for requirement source detection.

Usage:
    python test_requirement_source_service.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import app.services.requirement_source_service as source_service


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    previous_root = source_service.REQUIREMENTS_ROOT

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_service.REQUIREMENTS_ROOT = Path(tmp_dir) / "requirements"

            manual_root = source_service.REQUIREMENTS_ROOT / "MANUAL-1"
            _write_json(
                manual_root / "ticket.json",
                {
                    "ticket_id": "MANUAL-1",
                    "source": "web_manual",
                    "source_type": "manual",
                    "imported_from_jira": False,
                },
            )

            assert source_service.get_requirement_source("MANUAL-1") == "manual"
            assert not source_service.is_jira_requirement("MANUAL-1")
            assert not source_service.has_jira_snapshot("MANUAL-1")
            assert source_service.get_jira_key("MANUAL-1") is None

            jira_root = source_service.REQUIREMENTS_ROOT / "JIRA-1"
            _write_json(
                jira_root / "metadata.json",
                {
                    "ticket_id": "JIRA-1",
                    "source_type": "jira",
                    "jira_key": "JIRA-1",
                    "source_channel": "web",
                    "imported_from_jira": True,
                },
            )
            _write_json(
                jira_root / "snapshots" / "latest_jira_snapshot.json",
                {"metadata": {"ticket_id": "JIRA-1"}},
            )

            assert source_service.get_requirement_source("JIRA-1") == "jira"
            assert source_service.is_jira_requirement("JIRA-1")
            assert source_service.has_jira_snapshot("JIRA-1")
            assert source_service.get_jira_key("JIRA-1") == "JIRA-1"

            old_root = source_service.REQUIREMENTS_ROOT / "OLD-1"
            _write_json(
                old_root / "snapshots" / "jira_snapshot_v1.json",
                {"metadata": {"ticket_id": "OLD-1"}},
            )

            assert source_service.is_jira_requirement("OLD-1")
            assert source_service.has_jira_snapshot("OLD-1")

        print("PASS requirement source detection")
        return 0
    finally:
        source_service.REQUIREMENTS_ROOT = previous_root


if __name__ == "__main__":
    raise SystemExit(main())
