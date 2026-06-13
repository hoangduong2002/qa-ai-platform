"""Shared helpers for offline incremental Jira sync scripts.

The scripts in this repo are intentionally runnable with plain Python:

    python test_jira_delta_snapshot.py
    python test_jira_delta_compare.py
    python test_impact_mapping.py
    python test_incremental_merge.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "incremental"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / name


def print_summary(title: str, passed: int, failed: int = 0) -> None:
    total = passed + failed
    status = "PASS" if failed == 0 else "FAIL"
    print(f"[{status}] {title}: {passed}/{total} checks passed")


def assert_change_types(changes: list[dict[str, Any]], expected_types: set[str]) -> None:
    actual_types = {str(item.get("change_type") or "") for item in changes if isinstance(item, dict)}
    missing = sorted(expected_types - actual_types)
    if missing:
        raise AssertionError(f"Missing change types: {', '.join(missing)}")
