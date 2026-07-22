from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.services.quality_feedback.models import VersionMetadata


PROMPT_FILES = {
    "analyzer": "prompts/analyze_requirement.md",
    "generator_v1": "prompts/generate_function_testcases.md",
    "generator_v2": "prompts/generate_testcases_v2.md",
    "quality_reviewer": "prompts/review_testcases_v2_quality.md",
    "quality_corrector": "prompts/correct_testcases_v2_quality.md",
}


def prompt_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for name, raw_path in PROMPT_FILES.items():
        path = Path(raw_path)
        if path.exists():
            result[name] = f"{raw_path}#sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"
    return result


def model_configuration() -> dict[str, str]:
    """Return reproducibility settings only; credentials and endpoints are excluded."""
    names = (
        "PORTAL_DEFAULT_AI_MODE",
        "NON_PORTAL_AI_MODE",
        "DEEPSEEK_MODEL",
        "COPILOT_MODEL",
        "LOCAL_TEXT_MODEL",
        "TEST_QUALITY_REVIEW_AI_MODE",
        "TEST_QUALITY_REVIEW_MODEL",
        "TEST_QUALITY_CORRECTOR_AI_MODE",
        "TEST_QUALITY_CORRECTOR_MODEL",
    )
    return {name: os.getenv(name, "") for name in names if os.getenv(name, "").strip()}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def version_metadata(ticket_id: str, *, dataset_version: str = "") -> VersionMetadata:
    design = Path("requirements") / ticket_id / "test-design"
    quality = _json(design / "test_quality_report.json")
    generator = _json(design / "generator_comparison.json")
    quality_models = quality.get("model_metadata", {})
    model_identifiers: set[str] = set()
    if isinstance(quality_models, dict):
        for key in ("model", "model_identifier", "generator_model", "reviewer_model"):
            if quality_models.get(key):
                model_identifiers.add(str(quality_models[key]))
    usage_path = Path(os.getenv("AI_USAGE_LOG_PATH", "runtime/ai_usage_logs.jsonl"))
    if usage_path.exists():
        for line in usage_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("ticket_id") or "") != ticket_id:
                continue
            provider = str(record.get("provider") or "").strip()
            model = str(record.get("model") or "").strip()
            if provider or model:
                model_identifiers.add(f"{provider}:{model}".strip(":"))
    return VersionMetadata(
        dataset_version=dataset_version,
        analyzer_version=os.getenv("REQUIREMENT_ANALYZER_VERSION", "structured-analysis-v1"),
        generator_version=str(generator.get("generator_version") or os.getenv("TEST_CASE_GENERATOR_VERSION", "v1")),
        reviewer_version=str(quality.get("reviewer_version") or "test-quality-review-v1"),
        retrieval_version=os.getenv("KNOWLEDGE_RETRIEVAL_VERSION", "retrieval-v1"),
        ranking_version=os.getenv("KNOWLEDGE_RANKING_VERSION", "ranking-v1"),
        prompt_versions=prompt_versions(),
        model_identifiers=sorted(model_identifiers),
        model_configuration=model_configuration(),
    )
