from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config.env_loader import load_project_env

load_project_env()

from evaluation.golden import add_reviewed_ticket


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add one explicitly reviewed ticket to a versioned golden dataset")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--expected-json", required=True, help="GoldenTicket-compatible reviewed expectation JSON")
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--expectations-changed-reason", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected = json.loads(Path(args.expected_json).read_text(encoding="utf-8"))
    record = add_reviewed_ticket(
        dataset_name=args.dataset,
        ticket_id=args.ticket,
        expected_ticket=expected,
        reviewed_by=args.reviewed_by,
        change_reason=args.reason,
        expectations_changed_reason=args.expectations_changed_reason,
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
