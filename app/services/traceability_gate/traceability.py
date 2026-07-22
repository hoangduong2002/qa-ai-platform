from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.traceability_gate.models import (
    TraceabilityArtifactV1,
    TraceabilityEdge,
    TraceabilityIssue,
    TraceabilityNode,
    TraceNodeType,
)
from app.utils.artifact_loader import load_ticket_artifacts
from knowledge.storage.utils import atomic_write_json


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _stable_id(prefix: str, *parts) -> str:
    raw = "|".join(_clean(part).casefold() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return default


def _raw_id(item: dict, fallback: str) -> str:
    return _clean(
        item.get("id")
        or item.get("requirement_id")
        or item.get("criterion_id")
        or item.get("fact_id")
        or fallback
    )


def _label(item: dict) -> str:
    return _clean(
        item.get("description")
        or item.get("text")
        or item.get("statement")
        or item.get("title")
    )


def _items(payload: dict, section: str) -> list[dict]:
    rows = payload.get(section, []) if isinstance(payload, dict) else []
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


class _GraphBuilder:
    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        self.nodes: dict[str, TraceabilityNode] = {}
        self.edges: dict[str, TraceabilityEdge] = {}
        self.issues: dict[str, TraceabilityIssue] = {}
        self.object_nodes: dict[tuple[str, str], str] = {}

    def node(
        self,
        node_type: TraceNodeType,
        object_id: str,
        label: str,
        metadata: dict | None = None,
    ) -> str:
        object_id = _clean(object_id)
        node_id = f"{node_type.value.lower()}:{object_id}"
        if node_id not in self.nodes:
            self.nodes[node_id] = TraceabilityNode(
                node_id=node_id,
                node_type=node_type,
                object_id=object_id,
                label=_clean(label) or object_id,
                metadata=metadata or {},
            )
            self.object_nodes[(node_type.value, object_id)] = node_id
        return node_id

    def edge(self, source_id: str | None, target_id: str | None, relationship: str) -> None:
        if not source_id or not target_id:
            return
        if source_id not in self.nodes or target_id not in self.nodes:
            return
        edge_id = _stable_id("EDGE", source_id, target_id, relationship)
        self.edges[edge_id] = TraceabilityEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
        )

    def issue(self, category: str, object_id: str | None, explanation: str) -> None:
        blocker_id = _stable_id("TRB", category, object_id or "", explanation)
        self.issues[blocker_id] = TraceabilityIssue(
            blocker_id=blocker_id,
            category=category,
            object_id=object_id,
            explanation=explanation,
        )


def _analysis_sources(ticket_id: str, artifacts: dict) -> tuple[dict, dict]:
    summary = artifacts.get("requirement_summary") or {}
    structured = artifacts.get("structured_analysis") or {}
    enriched = artifacts.get("enriched_analysis") or {}
    approval = artifacts.get("enrichment_approval") or {}
    active = enriched if isinstance(approval, dict) and approval.get("approved") is True else structured
    return summary if isinstance(summary, dict) else {}, active if isinstance(active, dict) else {}


def _add_jira_and_requirement_nodes(
    graph: _GraphBuilder,
    ticket_id: str,
    summary: dict,
    analysis: dict,
) -> tuple[dict[str, str], set[str], set[str]]:
    raw_lookup: dict[str, str] = {}
    ac_ids: set[str] = set()
    business_rule_ids: set[str] = set()
    description_node = graph.node(
        TraceNodeType.JIRA_SOURCE_SECTION,
        ticket_id,
        f"Jira ticket {ticket_id}",
        {"section": "ticket"},
    )
    raw_lookup[ticket_id] = description_node

    section_specs = [
        ("validations", TraceNodeType.ACCEPTANCE_CRITERION, "acceptance_criteria"),
        ("acceptance_criteria", TraceNodeType.ACCEPTANCE_CRITERION, "acceptance_criteria"),
        ("business_rules", TraceNodeType.BUSINESS_RULE, "business_rules"),
    ]
    for section, node_type, section_name in section_specs:
        rows = [*_items(summary, section), *_items(analysis, section)]
        if not rows:
            continue
        section_node = graph.node(
            TraceNodeType.JIRA_SOURCE_SECTION,
            f"{ticket_id}:{section_name}",
            section_name.replace("_", " ").title(),
            {"section": section_name},
        )
        for index, item in enumerate(rows, start=1):
            object_id = _raw_id(item, f"{ticket_id}:{section_name}:{index}")
            item_node = graph.node(node_type, object_id, _label(item), {"section": section_name})
            raw_lookup[object_id] = item_node
            graph.edge(section_node, item_node, "contains")
            if node_type == TraceNodeType.ACCEPTANCE_CRITERION:
                ac_ids.add(item_node)
            else:
                business_rule_ids.add(item_node)

    for section in (
        "functional_requirements", "integrations", "error_handling",
        "non_functional_requirements", "expected_results", "permissions",
        "state_transitions",
    ):
        for index, item in enumerate([*_items(summary, section), *_items(analysis, section)], start=1):
            object_id = _raw_id(item, f"{ticket_id}:{section}:{index}")
            item_node = graph.node(
                TraceNodeType.JIRA_SOURCE_SECTION,
                object_id,
                _label(item),
                {"section": section},
            )
            raw_lookup[object_id] = item_node

    source_refs = analysis.get("source_references", []) if isinstance(analysis, dict) else []
    for index, ref in enumerate(source_refs if isinstance(source_refs, list) else [], start=1):
        if not isinstance(ref, dict):
            continue
        if str(ref.get("source_classification") or "") != "JIRA_ACCEPTANCE_CRITERIA":
            continue
        object_id = _clean(ref.get("source_identifier") or f"{ticket_id}:acceptance:{index}")
        if object_id in raw_lookup:
            continue
        node_id = graph.node(
            TraceNodeType.ACCEPTANCE_CRITERION,
            object_id,
            ref.get("source_excerpt") or object_id,
            {"section": "acceptance_criteria"},
        )
        raw_lookup[object_id] = node_id
        ac_ids.add(node_id)

    return raw_lookup, ac_ids, business_rule_ids


def build_traceability(
    *,
    ticket_id: str,
    testcases: list[dict],
    selected_testcase_version: str,
    persist: bool = True,
) -> TraceabilityArtifactV1:
    artifacts = load_ticket_artifacts(ticket_id)
    root = Path("requirements") / ticket_id
    summary, analysis = _analysis_sources(ticket_id, artifacts)
    graph = _GraphBuilder(ticket_id)
    source_lookup, ac_nodes, _ = _add_jira_and_requirement_nodes(
        graph, ticket_id, summary, analysis
    )

    approved_refs = [
        item for item in artifacts.get("selected_references", [])
        if isinstance(item, dict)
        and str(item.get("classification") or "").upper() == "ACCEPTED"
    ]
    approved_kb_lookup: dict[str, str] = {}
    for item in approved_refs:
        object_id = _clean(
            item.get("source_result_id") or item.get("result_id") or item.get("citation")
        )
        if not object_id:
            continue
        approved_kb_lookup[object_id] = graph.node(
            TraceNodeType.KNOWLEDGE_REFERENCE,
            object_id,
            item.get("citation") or item.get("excerpt") or object_id,
            {"classification": "ACCEPTED"},
        )

    clarification_payload = artifacts.get("clarification_answers") or {}
    clarification_rows = []
    if isinstance(clarification_payload, dict):
        for key in ("answers", "clarification_answers", "answered_clarifications"):
            if isinstance(clarification_payload.get(key), list):
                clarification_rows = clarification_payload[key]
                break
    elif isinstance(clarification_payload, list):
        clarification_rows = clarification_payload
    clarification_lookup = {}
    for index, item in enumerate(clarification_rows, start=1):
        if not isinstance(item, dict) or not _clean(item.get("answer") or item.get("response")):
            continue
        object_id = _clean(item.get("question_id") or item.get("id") or f"clarification-{index}")
        clarification_lookup[object_id] = graph.node(
            TraceNodeType.JIRA_SOURCE_SECTION,
            object_id,
            item.get("answer") or item.get("response"),
            {"section": "confirmed_clarification"},
        )

    coverage = artifacts.get("coverage_model") or {}
    coverage_lookup: dict[str, str] = {}
    mandatory_coverage_nodes: set[str] = set()
    for item in coverage.get("coverage_conditions", []) if isinstance(coverage, dict) else []:
        if not isinstance(item, dict) or not item.get("condition_id"):
            continue
        object_id = _clean(item["condition_id"])
        node_id = graph.node(
            TraceNodeType.COVERAGE_CONDITION,
            object_id,
            item.get("title") or object_id,
            {
                "mandatory": item.get("mandatory") is True,
                "condition_type": item.get("condition_type"),
            },
        )
        coverage_lookup[object_id] = node_id
        if item.get("mandatory") is True:
            mandatory_coverage_nodes.add(node_id)
        for ref in item.get("source_refs", []) or []:
            if not isinstance(ref, dict):
                continue
            source_id = _clean(ref.get("source_identifier") or "")
            graph.edge(source_lookup.get(source_id), node_id, "drives_coverage")

    scenarios = artifacts.get("scenarios") or []
    approved_scenarios = _read_json(root / "scenarios" / "approved_scenarios.json", [])
    if approved_scenarios:
        scenarios = approved_scenarios
    scenario_lookup: dict[str, str] = {}
    for item in scenarios if isinstance(scenarios, list) else []:
        if not isinstance(item, dict) or not item.get("scenario_id"):
            continue
        object_id = _clean(item["scenario_id"])
        node_id = graph.node(
            TraceNodeType.SCENARIO,
            object_id,
            item.get("title") or item.get("description") or object_id,
        )
        scenario_lookup[object_id] = node_id
        for coverage_id in (item.get("coverage_ids") or item.get("coverage_refs") or []):
            coverage_node = coverage_lookup.get(_clean(coverage_id))
            if coverage_node:
                graph.edge(coverage_node, node_id, "covered_by_scenario")
            else:
                graph.issue(
                    "INVALID_OR_STALE_ID",
                    object_id,
                    f"Scenario {object_id} references missing coverage condition {coverage_id}.",
                )

    testcase_lookup: dict[str, str] = {}
    expected_nodes: set[str] = set()
    for index, item in enumerate(testcases or [], start=1):
        if not isinstance(item, dict):
            continue
        object_id = _clean(item.get("test_case_id") or item.get("testcase_id") or f"missing-testcase-{index}")
        tc_node = graph.node(
            TraceNodeType.TEST_CASE,
            object_id,
            item.get("title") or object_id,
        )
        testcase_lookup[object_id] = tc_node
        requirement_edge_count = 0
        coverage_edge_count = 0
        requirement_refs = (
            item.get("requirement_refs")
            or item.get("related_requirement_ids")
            or item.get("related_requirements")
            or []
        )
        if isinstance(requirement_refs, str):
            requirement_refs = [requirement_refs]
        for raw_id in requirement_refs:
            source_node = source_lookup.get(_clean(raw_id))
            if source_node:
                graph.edge(source_node, tc_node, "covered_by_test_case")
                requirement_edge_count += 1
            else:
                graph.issue(
                    "INVALID_OR_STALE_ID",
                    object_id,
                    f"Test case {object_id} references missing requirement {raw_id}.",
                )
        for raw_id in item.get("coverage_refs") or item.get("coverage_ids") or []:
            coverage_node = coverage_lookup.get(_clean(raw_id))
            if coverage_node:
                graph.edge(coverage_node, tc_node, "covered_by_test_case")
                coverage_edge_count += 1
            else:
                graph.issue(
                    "INVALID_OR_STALE_ID",
                    object_id,
                    f"Test case {object_id} references missing coverage condition {raw_id}.",
                )
        if requirement_edge_count == 0 and coverage_edge_count == 0:
            graph.issue(
                "MISSING_TESTCASE_TRACEABILITY",
                object_id,
                f"Test case {object_id} has no valid requirement or coverage reference.",
            )

        scenario_refs = item.get("scenario_refs") or []
        if not scenario_refs and item.get("scenario_id"):
            scenario_refs = [item.get("scenario_id")]
        for raw_id in scenario_refs:
            scenario_node = scenario_lookup.get(_clean(raw_id))
            if scenario_node:
                graph.edge(scenario_node, tc_node, "implemented_by_test_case")
            else:
                graph.issue(
                    "INVALID_OR_STALE_ID",
                    object_id,
                    f"Test case {object_id} references missing scenario {raw_id}.",
                )

        for raw_id in item.get("knowledge_refs") or []:
            kb_node = approved_kb_lookup.get(_clean(raw_id))
            if kb_node:
                graph.edge(kb_node, tc_node, "supports_test_case")
            else:
                graph.issue(
                    "UNAPPROVED_KNOWLEDGE_REFERENCE",
                    object_id,
                    f"Test case {object_id} references Knowledge Base item {raw_id} that is not approved.",
                )

        expected_results = item.get("expected_results") or []
        for result_index, result in enumerate(expected_results, start=1):
            row = result if isinstance(result, dict) else {"expected_result": result}
            step = row.get("step_number") or result_index
            expected_id = f"{object_id}:ER:{step}:{result_index}"
            expected_node = graph.node(
                TraceNodeType.EXPECTED_RESULT,
                expected_id,
                row.get("expected_result") or str(result),
            )
            expected_nodes.add(expected_node)
            graph.edge(tc_node, expected_node, "has_expected_result")
            supported_edge_count = 0
            for ref in row.get("source_refs") or []:
                if not isinstance(ref, dict):
                    continue
                ref_type = str(ref.get("source_type") or "").upper()
                ref_id = _clean(ref.get("source_id") or ref.get("source_identifier") or "")
                source_node = None
                if ref_type == "JIRA":
                    source_node = source_lookup.get(ref_id)
                elif ref_type == "CONFIRMED_CLARIFICATION":
                    source_node = clarification_lookup.get(ref_id)
                elif ref_type == "KNOWLEDGE_BASE":
                    source_node = approved_kb_lookup.get(ref_id)
                    if source_node is None:
                        graph.issue(
                            "UNAPPROVED_KNOWLEDGE_REFERENCE",
                            expected_id,
                            f"Expected result {expected_id} cites unapproved Knowledge Base reference {ref_id}.",
                        )
                if source_node:
                    graph.edge(source_node, expected_node, "supports_expected_result")
                    supported_edge_count += 1
                else:
                    graph.issue(
                        "INVALID_OR_STALE_ID",
                        expected_id,
                        f"Expected result {expected_id} cites missing source {ref_type}:{ref_id}.",
                    )
            if supported_edge_count == 0:
                graph.issue(
                    "UNSUPPORTED_EXPECTED_RESULT",
                    expected_id,
                    f"Expected result {expected_id} has no authoritative or approved source.",
                )

    edge_values = list(graph.edges.values())
    for ac_node in ac_nodes:
        if not any(edge.source_id == ac_node and edge.relationship == "covered_by_test_case" for edge in edge_values):
            graph.issue(
                "UNCOVERED_ACCEPTANCE_CRITERION",
                graph.nodes[ac_node].object_id,
                f"Acceptance criterion {graph.nodes[ac_node].object_id} has no test case.",
            )
    for coverage_node in mandatory_coverage_nodes:
        if not any(edge.source_id == coverage_node and edge.relationship == "covered_by_scenario" for edge in edge_values):
            graph.issue(
                "UNCOVERED_MANDATORY_COVERAGE",
                graph.nodes[coverage_node].object_id,
                f"Mandatory coverage condition {graph.nodes[coverage_node].object_id} has no scenario.",
            )
    for scenario_id, scenario_node in scenario_lookup.items():
        if not any(edge.source_id == scenario_node and edge.relationship == "implemented_by_test_case" for edge in edge_values):
            graph.issue(
                "SCENARIO_WITHOUT_TEST_CASE",
                scenario_id,
                f"Scenario {scenario_id} has no test case.",
            )

    artifact = TraceabilityArtifactV1(
        ticket_id=ticket_id,
        selected_testcase_version=selected_testcase_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        nodes=list(graph.nodes.values()),
        edges=list(graph.edges.values()),
        validation_issues=list(graph.issues.values()),
        summary={
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "issue_count": len(graph.issues),
            "acceptance_criterion_count": len(ac_nodes),
            "mandatory_coverage_count": len(mandatory_coverage_nodes),
            "scenario_count": len(scenario_lookup),
            "test_case_count": len(testcase_lookup),
            "expected_result_count": len(expected_nodes),
            "approved_knowledge_reference_count": len(approved_kb_lookup),
        },
    )
    if persist:
        atomic_write_json(root / "traceability.json", artifact.model_dump(mode="json"))
    return artifact
