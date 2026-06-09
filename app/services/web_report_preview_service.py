from collections import defaultdict

from app.services.report_service import load_ai_usage_logs
from app.services.requirement_list_service import list_requirements
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.ai_usage_report import normalize_node_name


def _safe_number(value):
    return value or 0


def _round(value):
    return round(value or 0, 2)


def build_report_preview() -> dict:
    requirements = list_requirements()
    usage_logs = load_ai_usage_logs()

    total_input_tokens = sum(_safe_number(log.get("input_tokens")) for log in usage_logs)
    total_output_tokens = sum(_safe_number(log.get("output_tokens")) for log in usage_logs)
    total_tokens = sum(_safe_number(log.get("total_tokens")) for log in usage_logs)

    if not total_tokens:
        total_tokens = total_input_tokens + total_output_tokens

    total_duration = sum(_safe_number(log.get("duration_seconds")) for log in usage_logs)

    requirement_rows = []

    for item in requirements:
        ticket_id = item.get("ticket_id", "")
        artifacts = load_ticket_artifacts(ticket_id)

        ticket_logs = [
            log for log in usage_logs
            if log.get("ticket_id") == ticket_id
        ]

        input_tokens = sum(_safe_number(log.get("input_tokens")) for log in ticket_logs)
        output_tokens = sum(_safe_number(log.get("output_tokens")) for log in ticket_logs)
        ticket_total_tokens = sum(_safe_number(log.get("total_tokens")) for log in ticket_logs)

        if not ticket_total_tokens:
            ticket_total_tokens = input_tokens + output_tokens

        duration = sum(_safe_number(log.get("duration_seconds")) for log in ticket_logs)

        scenarios = artifacts.get("scenarios", []) or []
        testcases = (
            artifacts.get("improved_testcases")
            or artifacts.get("testcases")
            or []
        )
        session = artifacts.get("session", {}) or {}

        requirement_rows.append(
            {
                "ticket_id": ticket_id,
                "name": item.get("summary", ""),
                "created_at": item.get("created_at", ""),
                "status": item.get("status", ""),
                "scenario_count": len(scenarios),
                "testcase_count": len(testcases),
                "improve_iterations": session.get("improve_iterations", 0),
                "ai_request_count": len(ticket_logs),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": ticket_total_tokens,
                "duration_seconds": _round(duration),
            }
        )

    node_stats = defaultdict(
        lambda: {
            "node": "",
            "ai_request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "duration_seconds": 0,
        }
    )

    for log in usage_logs:
        node = normalize_node_name(
            log.get("node_name") or "unknown"
        )

        stat = node_stats[node]
        stat["node"] = node
        stat["ai_request_count"] += 1
        stat["input_tokens"] += _safe_number(log.get("input_tokens"))
        stat["output_tokens"] += _safe_number(log.get("output_tokens"))

        total = log.get("total_tokens")
        if total is None:
            total = _safe_number(log.get("input_tokens")) + _safe_number(log.get("output_tokens"))

        stat["total_tokens"] += _safe_number(total)
        stat["duration_seconds"] += _safe_number(log.get("duration_seconds"))

    node_rows = sorted(
        node_stats.values(),
        key=lambda row: row["total_tokens"],
        reverse=True,
    )

    for row in node_rows:
        row["duration_seconds"] = _round(row["duration_seconds"])

    recent_logs = sorted(
        usage_logs,
        key=lambda log: log.get("timestamp", ""),
        reverse=True,
    )[:100]

    log_rows = []

    for log in recent_logs:
        input_tokens = _safe_number(log.get("input_tokens"))
        output_tokens = _safe_number(log.get("output_tokens"))
        total = log.get("total_tokens")

        if total is None:
            total = input_tokens + output_tokens

        log_rows.append(
            {
                "timestamp": log.get("timestamp", ""),
                "ticket_id": log.get("ticket_id", ""),
                "node_name": log.get("node_name", ""),
                "provider": log.get("provider", ""),
                "model": log.get("model", ""),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total,
                "duration_seconds": _round(log.get("duration_seconds")),
                "prompt_chars": log.get("prompt_chars", ""),
                "response_chars": log.get("response_chars", ""),
            }
        )

    summary = {
        "requirement_count": len(requirements),
        "ai_request_count": len(usage_logs),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "duration_seconds": _round(total_duration),
        "node_count": len(node_rows),
    }

    return {
        "summary": summary,
        "requirement_rows": requirement_rows,
        "node_rows": node_rows,
        "log_rows": log_rows,
    }