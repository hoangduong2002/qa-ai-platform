from __future__ import annotations

import hashlib
import json
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.generation_orchestrator import build_structured_generation_state
from app.services.report_service import load_ai_usage_logs
from app.utils.artifact_loader import load_ticket_artifacts
from evaluation.metrics.deterministic import (
    calculate_aggregate_metrics,
    calculate_ticket_metrics,
)
from evaluation.schemas.golden_dataset import GoldenDataset, GoldenTicket
from app.services.quality_feedback.versions import model_configuration, prompt_versions as quality_prompt_versions
from graph.requirement_summary_graph import requirement_summary_graph
from graph.testcase_graph import graph as testcase_graph


PROMPT_FILES_BY_STEP = {
    "requirement_analysis": "prompts/analyze_requirement.md",
    "clarification_questions": "prompts/generate_clarifications.md",
    "requirement_summary": "prompts/generate_requirement_summary.md",
    "test_scope": "prompts/generate_test_scope.md",
    "scenarios": "prompts/generate_structure_batch_scenarios.md",
    "test_cases": "prompts/generate_function_testcases.md",
    "coverage_review": "prompts/function_coverage_review.md",
    "improve_test_cases": "prompts/improve_function_testcases.md",
    "final_coverage_review": "prompts/function_final_coverage_review.md",
}


@dataclass
class RunnerConfig:
    keep_workspace: bool = False


class WorkflowEvaluationRunner:
    def __init__(self, config: RunnerConfig | None = None):
        self.config = config or RunnerConfig()

    def _read_file_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    def _prompt_versions(self) -> dict[str, str]:
        versions: dict[str, str] = {}

        for step, relative_path in PROMPT_FILES_BY_STEP.items():
            path = Path(relative_path)
            if not path.exists():
                continue

            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            versions[step] = f"{relative_path}#sha256:{digest}"

        return versions

    def _seed_workspace(self, runtime_ticket_id: str, ticket: GoldenTicket) -> Path:
        root = Path("requirements") / runtime_ticket_id
        source_dir = root / "source"
        design_dir = root / "design"

        if root.exists():
            shutil.rmtree(root)

        source_dir.mkdir(parents=True, exist_ok=True)
        design_dir.mkdir(parents=True, exist_ok=True)

        ticket_payload = {
            "ticket_id": runtime_ticket_id,
            "summary": ticket.jira_source_data.get("summary", runtime_ticket_id),
            "source": "jira",
            "source_type": "jira",
            "imported_from_jira": True,
            **ticket.workspace_seed.ticket,
        }

        (root / "ticket.json").write_text(
            json.dumps(ticket_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        source_data = ticket.workspace_seed.source
        (source_dir / "description.md").write_text(
            source_data.get("description", ""),
            encoding="utf-8",
        )
        (source_dir / "comments.md").write_text(
            source_data.get("comments", ""),
            encoding="utf-8",
        )

        jira_requirement_md = (
            f"# Main Jira Ticket: {runtime_ticket_id}\n\n"
            f"## Summary\n{source_data.get('summary', ticket.jira_source_data.get('summary', ''))}\n\n"
            f"## Description\n{source_data.get('description', '')}\n\n"
            f"## Comments\n{source_data.get('comments', '')}\n"
        )

        (source_dir / "jira_requirement.md").write_text(
            jira_requirement_md,
            encoding="utf-8",
        )

        (root / "metadata.json").write_text(
            json.dumps(
                {
                    "ticket_id": runtime_ticket_id,
                    "source": f"jira:{runtime_ticket_id}",
                    "source_type": "jira",
                    "imported_from_jira": True,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        (design_dir / "approved_test_case_structure.json").write_text(
            json.dumps(
                ticket.workspace_seed.approved_test_case_structure,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return root

    def _extract_raw_jira_input(self, root: Path) -> dict[str, Any]:
        return {
            "ticket": json.loads(self._read_file_text(root / "ticket.json") or "{}"),
            "description": self._read_file_text(root / "source" / "description.md"),
            "comments": self._read_file_text(root / "source" / "comments.md"),
            "jira_requirement": self._read_file_text(root / "source" / "jira_requirement.md"),
        }

    def _extract_model_metadata(
        self,
        runtime_ticket_id: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> dict[str, Any]:
        logs = []

        for record in load_ai_usage_logs():
            if record.get("ticket_id") != runtime_ticket_id:
                continue

            timestamp_raw = record.get("timestamp")
            if not timestamp_raw:
                continue

            try:
                timestamp = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
            except ValueError:
                continue

            if started_at <= timestamp <= ended_at:
                logs.append(record)

        models = sorted(
            {
                f"{record.get('provider', '')}:{record.get('model', '')}"
                for record in logs
                if record.get("provider") or record.get("model")
            }
        )

        return {
            "model_identifiers": models,
            "ai_usage_records": logs,
            "prompt_identifiers": self._prompt_versions(),
        }

    def _runtime_ticket_id(self, ticket_id: str, run_id: str) -> str:
        return f"_EVAL_{ticket_id}_{run_id}"

    def run_ticket(self, ticket: GoldenTicket, run_id: str) -> dict[str, Any]:
        runtime_ticket_id = self._runtime_ticket_id(ticket.ticket_id, run_id)
        started_at = datetime.now().astimezone()
        workspace_root = self._seed_workspace(runtime_ticket_id, ticket)

        error: str | None = None
        success = True

        try:
            requirement_summary_graph.invoke({"ticket_id": runtime_ticket_id})

            initial_state = build_structured_generation_state(
                ticket_id=runtime_ticket_id,
                ai_mode=None,
                source_channel="evaluation",
            )
            initial_state["ticket_id"] = runtime_ticket_id
            initial_state["source_channel"] = "evaluation"

            testcase_graph.invoke(initial_state)
        except Exception as run_error:
            success = False
            error = str(run_error)
            traceback.print_exc()

        ended_at = datetime.now().astimezone()

        artifacts = load_ticket_artifacts(runtime_ticket_id)

        metrics = calculate_ticket_metrics(
            expected_business_rules=ticket.expected_business_rules,
            expected_results=ticket.expected_results,
            critical_scenarios=ticket.critical_scenarios,
            critical_test_cases=ticket.critical_test_cases,
            expected_missing_information=ticket.expected_missing_information,
            expected_contradictions=ticket.expected_contradictions,
            expected_ambiguities=ticket.expected_ambiguities,
            acceptance_criteria_required_items=ticket.expected_acceptance_criteria_coverage.required_items,
            forbidden_assumptions=ticket.forbidden_assumptions,
            analysis=artifacts.get("analysis", {}),
            structured_analysis=artifacts.get("structured_analysis", {}),
            scenarios=artifacts.get("scenarios", []),
            testcases=artifacts.get("testcases", []),
            workflow_failed=not success,
        )

        model_metadata = self._extract_model_metadata(
            runtime_ticket_id=runtime_ticket_id,
            started_at=started_at,
            ended_at=ended_at,
        )

        result = {
            "ticket_id": ticket.ticket_id,
            "domain": ticket.domain,
            "runtime_ticket_id": runtime_ticket_id,
            "success": success,
            "error": error,
            "duration_seconds": (ended_at - started_at).total_seconds(),
            "raw_jira_input": self._extract_raw_jira_input(workspace_root),
            "jira_source_data": ticket.jira_source_data,
            "requirement_analysis": artifacts.get("analysis", {}),
            "structured_requirement_analysis": artifacts.get("structured_analysis", {}),
            "clarification_questions": artifacts.get("clarifications", {}),
            "requirement_summary": artifacts.get("requirement_summary", {}),
            "test_scope": artifacts.get("test_scope", {}),
            "scenarios": artifacts.get("scenarios", []),
            "test_cases": artifacts.get("testcases", []),
            "coverage_review": artifacts.get("coverage_review", {}),
            "execution_exceptions": [error] if error else [],
            "metrics": metrics,
            "model_metadata": model_metadata,
            "expectations": {
                "expected_business_rules": ticket.expected_business_rules,
                "expected_ambiguities": ticket.expected_ambiguities,
                "expected_missing_information": ticket.expected_missing_information,
                "expected_contradictions": ticket.expected_contradictions,
                "critical_scenarios": ticket.critical_scenarios,
                "critical_test_cases": ticket.critical_test_cases,
                "forbidden_assumptions": ticket.forbidden_assumptions,
                "expected_acceptance_criteria_coverage": ticket.expected_acceptance_criteria_coverage.model_dump(),
                "evaluation_notes": ticket.evaluation_notes,
            },
        }

        if not self.config.keep_workspace:
            shutil.rmtree(workspace_root, ignore_errors=True)

        return result

    def run_dataset(
        self,
        dataset: GoldenDataset,
        run_id: str,
        ticket_filter: str | None = None,
    ) -> dict[str, Any]:
        selected_tickets = [
            ticket for ticket in dataset.tickets if ticket_filter is None or ticket.ticket_id == ticket_filter
        ]

        if ticket_filter and not selected_tickets:
            raise ValueError(f"Ticket {ticket_filter} was not found in dataset {dataset.dataset_id}.")

        ticket_results = [self.run_ticket(ticket, run_id=run_id) for ticket in selected_tickets]

        aggregate = calculate_aggregate_metrics([item["metrics"] for item in ticket_results])
        per_domain = {
            domain: calculate_aggregate_metrics(
                [item["metrics"] for item in ticket_results if item.get("domain") == domain]
            )
            for domain in sorted({str(item.get("domain") or "unspecified") for item in ticket_results})
        }

        return {
            "report_schema_version": "2.0",
            "run_id": run_id,
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.dataset_version,
            "generated_at": datetime.now().isoformat(),
            "tickets": ticket_results,
            "aggregate_metrics": aggregate,
            "per_domain_metrics": per_domain,
            "execution_mode": "live",
            "versions": {
                "dataset": dataset.dataset_version,
                "prompt_versions": quality_prompt_versions(),
                "model_identifiers": sorted({model for item in ticket_results for model in item.get("model_metadata", {}).get("model_identifiers", [])}),
                "model_configuration": model_configuration(),
                "analyzer": "structured-analysis-v1",
                "generator": "workflow-v1",
                "reviewer": "coverage-review-v1",
                "retrieval": "retrieval-v1",
                "ranking": "ranking-v1",
            },
            "detected_regressions": [],
            "execution_errors": [
                {"ticket_id": item["ticket_id"], "error": item["error"]}
                for item in ticket_results
                if item.get("error")
            ],
        }
