from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


CONSERVATIVE_EXPECTED = {
    "KNOWLEDGE_BASE_ENABLED": "true",
    "STRUCTURED_ANALYSIS_ENABLED": "true",
    "STRUCTURED_ANALYSIS_SHADOW_MODE": "false",
    "REQUIREMENT_QUALITY_GATE_ENABLED": "true",
    "REQUIREMENT_QUALITY_GATE_MODE": "warn",
    "KNOWLEDGE_RETRIEVAL_ENABLED": "true",
    "KNOWLEDGE_RETRIEVAL_SHADOW_MODE": "false",
    "KNOWLEDGE_REFERENCE_REVIEW_REQUIRED": "true",
    "KB_ANALYSIS_ENRICHMENT_MODE": "manual",
    "COVERAGE_MODEL_MODE": "shadow",
    "TEST_CASE_GENERATOR_VERSION": "v2-manual",
    "TEST_QUALITY_REVIEW_ENABLED": "true",
    "TEST_QUALITY_REVIEW_MODE": "warn",
    "TRACEABILITY_GATE_ENABLED": "true",
    "EXPORT_QUALITY_GATE_ENABLED": "false",
}

ROLLBACK_EXPECTED = {
    "KNOWLEDGE_BASE_ENABLED": "false",
    "STRUCTURED_ANALYSIS_ENABLED": "false",
    "REQUIREMENT_QUALITY_GATE_ENABLED": "false",
    "KNOWLEDGE_RETRIEVAL_ENABLED": "false",
    "KNOWLEDGE_REFERENCE_REVIEW_REQUIRED": "false",
    "KB_ANALYSIS_ENRICHMENT_MODE": "off",
    "COVERAGE_MODEL_MODE": "off",
    "TEST_CASE_GENERATOR_VERSION": "v1",
    "TEST_QUALITY_REVIEW_ENABLED": "false",
    "TRACEABILITY_GATE_ENABLED": "false",
    "EXPORT_QUALITY_GATE_ENABLED": "false",
}

REQUIRED_AUTHORIZATION = (
    "KNOWLEDGE_BASE_MAINTAINER_TOKEN",
    "KNOWLEDGE_REFERENCE_REVIEWER_IDS",
    "QA_FEEDBACK_REVIEWER_IDS",
    "GOLDEN_DATASET_REVIEWER_IDS",
)

SECRET_KEYS = {"KNOWLEDGE_BASE_MAINTAINER_TOKEN"}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _normalized(config: dict[str, str], key: str) -> str:
    return str(config.get(key, "")).strip().lower()


def _is_configured(value: str) -> bool:
    clean = str(value or "").strip()
    return bool(clean) and not (clean.startswith("<") and clean.endswith(">"))


def validate_feature_flags(config: dict[str, str], profile: str) -> dict[str, Any]:
    if profile not in {"conservative", "rollback"}:
        raise ValueError("profile must be conservative or rollback")
    expected = CONSERVATIVE_EXPECTED if profile == "conservative" else ROLLBACK_EXPECTED
    errors: list[str] = []
    warnings: list[str] = []
    for key, wanted in expected.items():
        actual = _normalized(config, key)
        if actual != wanted:
            errors.append(f"{key} must be {wanted!r} for the {profile} profile; found {actual or '<unset>'!r}.")

    if profile == "conservative":
        if _normalized(config, "KB_ANALYSIS_ENRICHMENT_MODE") == "automatic":
            errors.append("Automatic KB enrichment is not allowed in the initial rollout.")
        if _normalized(config, "TEST_CASE_GENERATOR_VERSION") == "v2":
            errors.append("V2-only generation is not allowed in the initial rollout.")
        if _normalized(config, "EXPORT_QUALITY_GATE_ENABLED") == "true":
            errors.append("Blocking export must remain disabled in the initial rollout.")
        for key in REQUIRED_AUTHORIZATION:
            if not _is_configured(config.get(key, "")):
                errors.append(f"{key} must be supplied through deployment configuration or a secret store.")
        if _normalized(config, "EXPORT_QUALITY_GATE_MODE") == "block":
            warnings.append("EXPORT_QUALITY_GATE_MODE=block is dormant while EXPORT_QUALITY_GATE_ENABLED=false; keep warn for clarity.")

    rollback_controls = {
        "original_requirement_analysis": _normalized(config, "STRUCTURED_ANALYSIS_ENABLED") == "false" and _normalized(config, "REQUIREMENT_QUALITY_GATE_ENABLED") == "false",
        "no_knowledge_retrieval": _normalized(config, "KNOWLEDGE_RETRIEVAL_ENABLED") == "false",
        "generator_v1": _normalized(config, "TEST_CASE_GENERATOR_VERSION") == "v1",
        "no_reviewer": _normalized(config, "TEST_QUALITY_REVIEW_ENABLED") == "false",
        "original_export_behavior": _normalized(config, "TRACEABILITY_GATE_ENABLED") == "false" and _normalized(config, "EXPORT_QUALITY_GATE_ENABLED") == "false",
    }
    return {
        "profile": profile,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "rollback_controls": rollback_controls,
    }


def verify_fts5() -> dict[str, Any]:
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE rollout_fts_check USING fts5(content)")
        connection.close()
        return {"supported": True, "error": None}
    except sqlite3.Error as error:
        return {"supported": False, "error": str(error)}


def inspect_knowledge_root(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"root": str(root), "exists": False, "knowledge_bases": [], "healthy": False}
    bases = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("_")):
        index = directory / "indexes" / "search.db"
        manifest = directory / "indexes" / "index_manifest.json"
        bases.append({
            "kb_id": directory.name,
            "metadata_exists": (directory / "knowledge_base.json").exists(),
            "index_exists": index.exists(),
            "manifest_exists": manifest.exists(),
        })
    return {
        "root": str(root),
        "exists": True,
        "knowledge_bases": bases,
        "healthy": all(item["metadata_exists"] and item["index_exists"] and item["manifest_exists"] for item in bases),
    }


def inspect_ticket_artifacts(ticket_id: str, requirements_root: Path = Path("requirements")) -> dict[str, Any]:
    root = requirements_root / ticket_id
    paths = {
        "authoritative_analysis": root / "analysis" / "requirement_analysis.json",
        "structured_analysis": root / "analysis" / "structured_analysis.json",
        "quality_report": root / "analysis" / "quality_report.json",
        "approved_references": root / "knowledge" / "selected_references.json",
        "coverage_model": root / "test-design" / "coverage_model.json",
        "v1_testcases": root / "test-design" / "testcases_v1.json",
        "v2_testcases": root / "test-design" / "testcases_v2.json",
        "generator_comparison": root / "test-design" / "generator_comparison.json",
        "reviewer_report": root / "test-design" / "test_quality_report.json",
        "traceability": root / "traceability.json",
    }
    return {"ticket_id": ticket_id, "exists": root.exists(), "artifacts": {name: path.exists() for name, path in paths.items()}}


def inspect_evaluation_report(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"available": False, "path": str(path) if path else None}
    payload = json.loads(path.read_text(encoding="utf-8"))
    regressions = payload.get("detected_regressions", [])
    return {
        "available": True,
        "path": str(path),
        "dataset_id": payload.get("dataset_id"),
        "dataset_version": payload.get("dataset_version"),
        "versions": payload.get("versions", {}),
        "aggregate_metrics": payload.get("aggregate_metrics", {}),
        "critical_regressions": [item for item in regressions if item.get("critical")],
    }


def build_readiness_report(
    config: dict[str, str],
    *,
    profile: str,
    ticket_id: str | None = None,
    evaluation_report: Path | None = None,
    project_root: Path = Path("."),
) -> dict[str, Any]:
    validation = validate_feature_flags(config, profile)
    kb_root = Path(config.get("KNOWLEDGE_BASE_ROOT", "knowledge_bases"))
    if not kb_root.is_absolute():
        kb_root = project_root / kb_root
    fts = verify_fts5()
    if profile == "conservative" and not fts["supported"]:
        validation["valid"] = False
        validation["errors"].append("SQLite FTS5 support is required when Knowledge Base retrieval is enabled.")
    kb_health = inspect_knowledge_root(kb_root)
    if profile == "conservative" and _normalized(config, "KNOWLEDGE_BASE_ENABLED") == "true":
        if not kb_health["exists"]:
            validation["valid"] = False
            validation["errors"].append(f"Knowledge Base root does not exist: {kb_root}")
        elif not kb_health["knowledge_bases"]:
            validation["warnings"].append("Knowledge Base root contains no configured knowledge bases.")
        elif not kb_health["healthy"]:
            validation["valid"] = False
            validation["errors"].append("One or more Knowledge Bases is missing metadata, its index, or index manifest.")
    evaluation = inspect_evaluation_report(evaluation_report)
    if profile == "conservative":
        if not evaluation.get("available"):
            validation["warnings"].append("No evaluation report was supplied; attach the release candidate report before approval.")
        elif evaluation.get("critical_regressions"):
            validation["valid"] = False
            validation["errors"].append("The supplied evaluation report contains critical regressions.")
    ticket_artifacts = inspect_ticket_artifacts(ticket_id) if ticket_id else None
    if ticket_artifacts and ticket_artifacts["exists"]:
        missing = [name for name, exists in ticket_artifacts["artifacts"].items() if not exists]
        if missing:
            validation["warnings"].append(
                "Selected rollout ticket is missing comparison/readiness artifacts: " + ", ".join(missing)
            )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "validation": validation,
        "fts5": fts,
        "knowledge_base_health": kb_health,
        "evaluation": evaluation,
        "ticket_artifacts": ticket_artifacts,
        "configuration": {
            key: "[REDACTED]" if key in SECRET_KEYS and value else value
            for key, value in config.items()
            if key in set(CONSERVATIVE_EXPECTED) | set(ROLLBACK_EXPECTED) | set(REQUIRED_AUTHORIZATION) | {"KNOWLEDGE_BASE_ROOT"}
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate production rollout or code-free rollback configuration")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--profile", choices=["conservative", "rollback"], required=True)
    parser.add_argument("--ticket", default=None)
    parser.add_argument("--evaluation-report", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = build_readiness_report(
        load_env_file(Path(args.env_file)),
        profile=args.profile,
        ticket_id=args.ticket,
        evaluation_report=Path(args.evaluation_report) if args.evaluation_report else None,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["validation"]["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
