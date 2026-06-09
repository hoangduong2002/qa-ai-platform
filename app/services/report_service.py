import json
from pathlib import Path
from datetime import datetime
from openpyxl import Workbook
from app.services.requirement_list_service import list_requirements
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.ai_usage_report import normalize_node_name


def load_ai_usage_logs():
    log_file = Path("reports") / "ai_usage_logs.jsonl"

    if not log_file.exists():
        return []

    logs = []

    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        logs.append(json.loads(line))

    return logs


def generate_system_report():
    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = (
        output_dir
        / f"qa_ai_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    requirements = list_requirements()
    usage_logs = load_ai_usage_logs()

    wb = Workbook()

    ws = wb.active
    ws.title = "Requirement Summary"

    ws.append(
        [
            "Requirement ID",
            "Name",
            "Created At",
            "Status",
            "Scenario Count",
            "Test Case Count",
            "Improve Iterations",
            "AI Request Count",
            "Input Tokens",
            "Output Tokens",
            "Total Tokens",
            "Total AI Duration Seconds"
        ]
    )

    for item in requirements:
        ticket_id = item["ticket_id"]

        artifacts = load_ticket_artifacts(ticket_id)

        ticket_logs = [
            log for log in usage_logs
            if log.get("ticket_id") == ticket_id
        ]

        input_tokens = sum(
            log.get("input_tokens") or 0
            for log in ticket_logs
        )

        output_tokens = sum(
            log.get("output_tokens") or 0
            for log in ticket_logs
        )

        duration = sum(
            log.get("duration_seconds") or 0
            for log in ticket_logs
        )

        scenarios = artifacts.get("scenarios", [])
        testcases = (
            artifacts.get("improved_testcases")
            or artifacts.get("testcases", [])
        )

        session = artifacts.get("session", {})

        ws.append(
            [
                ticket_id,
                item.get("summary", ""),
                item.get("created_at", ""),
                item.get("status", ""),
                len(scenarios),
                len(testcases),
                session.get("improve_iterations", 0),
                len(ticket_logs),
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
                round(duration, 2)
            ]
        )

    ws_logs = wb.create_sheet("AI Usage Logs")

    ws_logs.append(
        [
            "Timestamp",
            "Requirement ID",
            "Node",
            "Provider",
            "Model",
            "Input Tokens",
            "Output Tokens",
            "Total Tokens",
            "Duration Seconds",
            "Prompt Chars",
            "Response Chars"
        ]
    )

    for log in usage_logs:
        ws_logs.append(
            [
                log.get("timestamp", ""),
                log.get("ticket_id", ""),
                log.get("node_name", ""),
                log.get("provider", ""),
                log.get("model", ""),
                log.get("input_tokens", ""),
                log.get("output_tokens", ""),
                log.get("total_tokens", ""),
                log.get("duration_seconds", ""),
                log.get("prompt_chars", ""),
                log.get("response_chars", "")
            ]
        )
        
    ws_node = wb.create_sheet(
        "AI Usage by Node"
    )

    ws_node.append(
        [
            "Node",
            "AI Request Count",
            "Input Tokens",
            "Output Tokens",
            "Total Tokens",
            "Total Duration Seconds"
        ]
    )

    node_stats = {}

    for log in usage_logs:
        node = normalize_node_name(
            log.get("node_name", "unknown")
        )

        if node not in node_stats:
            node_stats[node] = {
                "count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration": 0
            }

        node_stats[node]["count"] += 1
        node_stats[node]["input_tokens"] += (
            log.get("input_tokens") or 0
        )
        node_stats[node]["output_tokens"] += (
            log.get("output_tokens") or 0
        )
        node_stats[node]["duration"] += (
            log.get("duration_seconds") or 0
        )

    for node, stat in sorted(
        node_stats.items(),
        key=lambda x: (
            x[1]["input_tokens"]
            + x[1]["output_tokens"]
        ),
        reverse=True
    ):
        total_tokens = (
            stat["input_tokens"]
            + stat["output_tokens"]
        )

        ws_node.append(
            [
                node,
                stat["count"],
                stat["input_tokens"],
                stat["output_tokens"],
                total_tokens,
                round(stat["duration"], 2)
            ]
        )

    wb.save(output_file)
    
    

    return str(output_file)