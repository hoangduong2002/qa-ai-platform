from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.state import QAState
from app.services.coverage_model.config import coverage_model_mode
from app.services.knowledge_reference_review.retrieval_config import (
    knowledge_retrieval_enabled,
    knowledge_retrieval_shadow_mode,
)
from app.services.knowledge_reference_review.service import create_review_request
from app.services.requirement_enrichment.config import enrichment_mode
from app.services.requirement_quality.config import quality_gate_enabled, quality_gate_mode
from app.services.rollout_readiness import (
    build_readiness_report,
    load_env_file,
    validate_feature_flags,
    verify_fts5,
)
from app.services.structured_requirement_analysis_service import (
    structured_analysis_enabled,
    structured_analysis_shadow_mode,
)
from app.services.test_case_generator_v2.config import test_case_generator_version as generator_version_setting
from app.services.test_quality_review.config import test_quality_review_mode as quality_review_mode_setting
from app.services.traceability_gate.config import (
    export_quality_gate_enabled,
    traceability_gate_enabled,
)
from evaluation.schemas.golden_dataset import load_dataset
from knowledge.services.knowledge_services import KnowledgeServiceFacade


ROOT = Path(__file__).parents[1]


def _production_config() -> dict[str, str]:
    config = load_env_file(ROOT / "config" / "production-rollout.env")
    config.update({
        "KNOWLEDGE_BASE_MAINTAINER_TOKEN": "configured-token",
        "KNOWLEDGE_REFERENCE_REVIEWER_IDS": "qa.reference",
        "QA_FEEDBACK_REVIEWER_IDS": "qa.reviewer",
        "GOLDEN_DATASET_REVIEWER_IDS": "qa.lead",
    })
    return config


def _apply(monkeypatch, config: dict[str, str]) -> None:
    for key, value in config.items():
        monkeypatch.setenv(key, value)


def test_conservative_feature_flag_matrix(monkeypatch) -> None:
    config = _production_config()
    _apply(monkeypatch, config)
    assert structured_analysis_enabled() is True
    assert structured_analysis_shadow_mode() is False
    assert quality_gate_enabled() is True
    assert quality_gate_mode().value == "warn"
    assert knowledge_retrieval_enabled() is True
    assert knowledge_retrieval_shadow_mode() is False
    assert enrichment_mode().value == "manual"
    assert coverage_model_mode().value == "shadow"
    assert generator_version_setting().value == "v2-manual"
    assert quality_review_mode_setting().value == "warn"
    assert traceability_gate_enabled() is True
    assert export_quality_gate_enabled() is False


def test_rollback_profile_restores_all_independent_paths(monkeypatch) -> None:
    config = load_env_file(ROOT / "config" / "rollback.env")
    result = validate_feature_flags(config, "rollback")
    assert result["valid"] is True
    assert all(result["rollback_controls"].values())
    _apply(monkeypatch, config)
    assert structured_analysis_enabled() is False
    assert knowledge_retrieval_enabled() is False
    assert generator_version_setting().value == "v1"
    assert quality_review_mode_setting().value == "off"
    assert traceability_gate_enabled() is False
    assert export_quality_gate_enabled() is False


def test_initial_rollout_rejects_unsafe_or_unconfigured_values() -> None:
    config = load_env_file(ROOT / "config" / "production-rollout.env")
    config["KB_ANALYSIS_ENRICHMENT_MODE"] = "automatic"
    config["TEST_CASE_GENERATOR_VERSION"] = "v2"
    config["EXPORT_QUALITY_GATE_ENABLED"] = "true"
    result = validate_feature_flags(config, "conservative")
    assert result["valid"] is False
    joined = " ".join(result["errors"])
    assert "Automatic KB enrichment" in joined
    assert "V2-only" in joined
    assert "Blocking export" in joined
    assert "KNOWLEDGE_BASE_MAINTAINER_TOKEN" in joined


def test_retrieval_kill_switch_prevents_provider_call(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_ENABLED", "false")

    def _provider(*_args, **_kwargs):
        raise AssertionError("provider must not be called")

    with pytest.raises(RuntimeError, match="disabled"):
        create_review_request(
            ticket_id="T-1", kb_id="KB1", query="fee", retrieval_need="fee",
            jira_issue_being_clarified="AC-1", reviewer_id="qa", search_provider=_provider,
        )


def test_readiness_report_checks_health_evaluation_and_redacts_secret(tmp_path) -> None:
    config = _production_config()
    config["KNOWLEDGE_BASE_ROOT"] = "data/kb"
    kb = tmp_path / "data" / "kb" / "KB1"
    (kb / "indexes").mkdir(parents=True)
    (kb / "knowledge_base.json").write_text("{}", encoding="utf-8")
    (kb / "indexes" / "search.db").write_bytes(b"fixture")
    (kb / "indexes" / "index_manifest.json").write_text("{}", encoding="utf-8")
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({
        "dataset_id": "golden", "dataset_version": "1.0.0", "versions": {},
        "aggregate_metrics": {"schema_valid_response_rate": 1.0},
        "detected_regressions": [],
    }), encoding="utf-8")
    report = build_readiness_report(
        config, profile="conservative", evaluation_report=evaluation, project_root=tmp_path
    )
    assert report["validation"]["valid"] is True
    assert report["fts5"]["supported"] is True
    assert report["knowledge_base_health"]["healthy"] is True
    assert report["configuration"]["KNOWLEDGE_BASE_MAINTAINER_TOKEN"] == "[REDACTED]"


def test_qa_state_is_backward_compatible() -> None:
    assert QAState.__required_keys__ == {"ticket_id"}
    for key in ("structured_analysis", "enrichment", "coverage_model", "testcases_v2", "test_quality_report"):
        assert key in QAState.__optional_keys__


def test_clean_install_primitives_work_in_empty_directory(tmp_path) -> None:
    assert verify_fts5()["supported"] is True
    service = KnowledgeServiceFacade(tmp_path / "knowledge_bases")
    service.create_kb("KB1", "Clean install", "", "installer")
    service.create_collection("KB1", "rules", "Rules", "", 10, "installer")
    assert service.kb_health("KB1")["fts5_supported"] is True
    dataset = load_dataset(ROOT / "evaluation" / "datasets" / "weclever_golden" / "dataset.json")
    assert dataset.tickets
