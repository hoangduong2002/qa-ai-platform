from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.check import diagnose_configuration
from app.config.env_loader import ENV_FILE_NAMES, load_project_env, read_environment_layers


def _write(root: Path, filename: str, content: str) -> None:
    (root / filename).write_text(content.strip() + "\n", encoding="utf-8")


def test_env_only(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "APP_TIMEZONE=UTC\nLOG_LEVEL=INFO")
    target: dict[str, str] = {}
    result = load_project_env(tmp_path, target)
    assert target == {"APP_TIMEZONE": "UTC", "LOG_LEVEL": "INFO"}
    assert result.found_files == (".env",)
    assert set(result.missing_files) == set(ENV_FILE_NAMES[1:])


def test_env_plus_ai(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "APP_TIMEZONE=UTC")
    _write(tmp_path, ".env.ai", "PORTAL_DEFAULT_AI_MODE=NO_LLM")
    merged, sources, _, _ = read_environment_layers(tmp_path)
    assert merged["PORTAL_DEFAULT_AI_MODE"] == "NO_LLM"
    assert sources["PORTAL_DEFAULT_AI_MODE"] == ".env.ai"


def test_env_plus_qa(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "APP_TIMEZONE=UTC")
    _write(tmp_path, ".env.qa", "TEST_CASE_GENERATOR_VERSION=v2-manual")
    target: dict[str, str] = {}
    load_project_env(tmp_path, target)
    assert target["TEST_CASE_GENERATOR_VERSION"] == "v2-manual"


def test_all_four_files_and_later_file_precedence(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "LOG_LEVEL=BASE\nDEEPSEEK_API_KEY=base")
    _write(tmp_path, ".env.ai", "LOG_LEVEL=AI")
    _write(tmp_path, ".env.qa", "LOG_LEVEL=QA")
    _write(tmp_path, ".env.secrets", "LOG_LEVEL=SECRET\nDEEPSEEK_API_KEY=secret")
    target: dict[str, str] = {}
    result = load_project_env(tmp_path, target)
    assert target["LOG_LEVEL"] == "SECRET"
    assert target["DEEPSEEK_API_KEY"] == "secret"
    assert result.file_sources["LOG_LEVEL"] == ".env.secrets"


def test_missing_optional_files_are_safe(tmp_path: Path) -> None:
    target: dict[str, str] = {}
    result = load_project_env(tmp_path, target)
    assert target == {}
    assert set(result.missing_files) == set(ENV_FILE_NAMES)


def test_process_environment_overrides_every_file(tmp_path: Path) -> None:
    for filename in ENV_FILE_NAMES:
        _write(tmp_path, filename, f"LOG_LEVEL={filename}")
    target = {"LOG_LEVEL": "PROCESS"}
    result = load_project_env(tmp_path, target)
    assert target["LOG_LEVEL"] == "PROCESS"
    assert result.process_override_keys == ("LOG_LEVEL",)


def test_secret_layer_overrides_earlier_only_without_process_value(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "DEEPSEEK_API_KEY=base")
    _write(tmp_path, ".env.secrets", "DEEPSEEK_API_KEY=secret")
    no_process: dict[str, str] = {}
    load_project_env(tmp_path, no_process)
    assert no_process["DEEPSEEK_API_KEY"] == "secret"
    with_process = {"DEEPSEEK_API_KEY": "process"}
    load_project_env(tmp_path, with_process)
    assert with_process["DEEPSEEK_API_KEY"] == "process"


def test_empty_later_value_is_preserved_consistently(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "NON_PORTAL_AI_MODE=DEEPSEEK_ONLY")
    _write(tmp_path, ".env.ai", "NON_PORTAL_AI_MODE=")
    merged, sources, _, _ = read_environment_layers(tmp_path)
    assert merged["NON_PORTAL_AI_MODE"] == ""
    assert sources["NON_PORTAL_AI_MODE"] == ".env.ai"


def test_duplicate_and_misplaced_keys_are_detected(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "PORTAL_DEFAULT_AI_MODE=NO_LLM")
    _write(tmp_path, ".env.ai", "PORTAL_DEFAULT_AI_MODE=NO_LLM")
    report = diagnose_configuration(tmp_path, {})
    assert report["duplicates"]["PORTAL_DEFAULT_AI_MODE"] == [".env", ".env.ai"]
    assert "PORTAL_DEFAULT_AI_MODE" in report["misplaced_keys"][".env"]
    assert report["valid"] is False


def test_duplicate_with_different_values_is_detected(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "LOG_LEVEL=INFO")
    _write(tmp_path, ".env.ai", "LOG_LEVEL=DEBUG")
    report = diagnose_configuration(tmp_path, {})
    assert report["duplicates"]["LOG_LEVEL"] == [".env", ".env.ai"]
    assert report["effective_configuration"]["LOG_LEVEL"]["value"] == "DEBUG"


def test_unknown_qa_flag_and_invalid_enum_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".env.qa",
        "UNKNOWN_QA_FLAG=true\nTEST_CASE_GENERATOR_VERSION=v3",
    )
    report = diagnose_configuration(tmp_path, {})
    assert report["unknown_keys"] == {".env.qa": ["UNKNOWN_QA_FLAG"]}
    assert report["invalid_enum_values"][0]["variable"] == "TEST_CASE_GENERATOR_VERSION"


def test_no_llm_requires_no_provider_credentials(tmp_path: Path) -> None:
    _write(tmp_path, ".env.ai", "PORTAL_DEFAULT_AI_MODE=NO_LLM")
    report = diagnose_configuration(tmp_path, {})
    assert report["active_ai_routing"]["PORTAL_DEFAULT_AI_MODE"] == "NO_LLM"
    assert report["credentials"]["DEEPSEEK_API_KEY"] == "not configured"
    assert report["credentials"]["COPILOT_API_KEY"] == "not configured"
    assert report["valid"] is True


def test_deprecated_ai_mode_is_reported_but_remains_compatible(tmp_path: Path) -> None:
    _write(tmp_path, ".env.ai", "PORTAL_DEFAULT_AI_MODE=PRODUCTION_HYBRID")
    report = diagnose_configuration(tmp_path, {})
    assert report["deprecated_ai_modes"] == [
        {"variable": "PORTAL_DEFAULT_AI_MODE", "value": "PRODUCTION_HYBRID"}
    ]
    assert report["invalid_enum_values"] == []


@pytest.mark.parametrize(
    ("mode", "credential"),
    [("DEEPSEEK_ONLY", "DEEPSEEK_API_KEY"), ("COPILOT_ONLY", "COPILOT_API_KEY")],
)
def test_remote_mode_reports_missing_key_without_secret_value(tmp_path: Path, mode: str, credential: str) -> None:
    _write(tmp_path, ".env.ai", f"PORTAL_DEFAULT_AI_MODE={mode}")
    report = diagnose_configuration(tmp_path, {})
    rendered = json.dumps(report)
    assert report["credentials"][credential] == "not configured"
    assert "super-secret-value" not in rendered


@pytest.mark.parametrize(
    ("auth_mode", "secret_values", "expected"),
    [
        ("PAT", "JIRA_PAT=pat-value", {"JIRA_PAT": "configured"}),
        ("BASIC", "JIRA_USERNAME=user\nJIRA_PASSWORD=password", {"JIRA_USERNAME": "configured", "JIRA_PASSWORD": "configured"}),
    ],
)
def test_jira_credentials_resolve_from_secret_layer(tmp_path: Path, auth_mode: str, secret_values: str, expected: dict[str, str]) -> None:
    _write(tmp_path, ".env", f"JIRA_AUTH_MODE={auth_mode}")
    _write(tmp_path, ".env.secrets", secret_values)
    report = diagnose_configuration(tmp_path, {})
    for key, status in expected.items():
        assert report["credentials"][key] == status
        assert report["effective_configuration"][key]["value"] == status


def test_safe_qa_rollout_resolves_exact_modes(tmp_path: Path) -> None:
    source = Path(".env.qa.example").read_text(encoding="utf-8") if Path(".env.qa.example").exists() else """
KNOWLEDGE_BASE_ENABLED=true
STRUCTURED_ANALYSIS_ENABLED=true
STRUCTURED_ANALYSIS_SHADOW_MODE=false
REQUIREMENT_QUALITY_GATE_ENABLED=true
REQUIREMENT_QUALITY_GATE_MODE=warn
KNOWLEDGE_RETRIEVAL_ENABLED=true
KNOWLEDGE_RETRIEVAL_SHADOW_MODE=false
KNOWLEDGE_REFERENCE_REVIEW_REQUIRED=true
KB_ANALYSIS_ENRICHMENT_MODE=manual
COVERAGE_MODEL_MODE=shadow
TEST_CASE_GENERATOR_VERSION=v2-manual
TEST_QUALITY_REVIEW_ENABLED=true
TEST_QUALITY_REVIEW_MODE=warn
TRACEABILITY_GATE_ENABLED=true
EXPORT_QUALITY_GATE_ENABLED=false
EXPORT_QUALITY_GATE_MODE=warn
"""
    _write(tmp_path, ".env.qa", source)
    report = diagnose_configuration(tmp_path, {})
    expected = {
        "STRUCTURED_ANALYSIS_ENABLED": "true",
        "REQUIREMENT_QUALITY_GATE_MODE": "warn",
        "KNOWLEDGE_RETRIEVAL_ENABLED": "true",
        "KB_ANALYSIS_ENRICHMENT_MODE": "manual",
        "COVERAGE_MODEL_MODE": "shadow",
        "TEST_CASE_GENERATOR_VERSION": "v2-manual",
        "TEST_QUALITY_REVIEW_MODE": "warn",
        "TRACEABILITY_GATE_ENABLED": "true",
        "EXPORT_QUALITY_GATE_ENABLED": "false",
    }
    for key, value in expected.items():
        assert report["active_qa_rollout"][key] == value


def test_secret_values_never_appear_in_diagnostic_output(tmp_path: Path) -> None:
    secret = "never-print-this-secret"
    _write(tmp_path, ".env.secrets", f"DEEPSEEK_API_KEY={secret}")
    rendered = json.dumps(diagnose_configuration(tmp_path, {}))
    assert secret not in rendered
    assert '"DEEPSEEK_API_KEY": "configured"' in rendered
