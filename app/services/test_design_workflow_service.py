import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from app.application.generation_orchestrator import (
    build_structured_generation_state,
    prepare_generation,
)
from app.application.response_models import AppResult
from app.exporters.function_based_excel_exporter import (
    export_function_based_testcases_to_excel,
)
from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.review_session import save_review_session
from app.utils.test_structure_store import load_approved_test_case_structure
from graph.nodes.generate_scenarios import generate_scenarios
from graph.nodes.generate_test_scope import generate_test_scope
from graph.nodes.generate_testcases import generate_testcases
from graph.test_generation_graph import test_generation_graph


logger = logging.getLogger(__name__)


def _root(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id


def _scenario_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "scenarios"


def _testcase_dir(ticket_id: str) -> Path:
    return _root(ticket_id) / "testcases"


def _scenario_session_file(ticket_id: str) -> Path:
    return _scenario_dir(ticket_id) / "scenario_session.json"


def _testcase_session_file(ticket_id: str) -> Path:
    return _testcase_dir(ticket_id) / "testcase_session.json"


def _read_json(file_path: Path, default: Any):
    if not file_path.exists():
        return default

    return json.loads(file_path.read_text(encoding="utf-8"))


def _write_json(file_path: Path, data: Any) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(file_path)


def _version_number(version: str) -> int:
    if re.match(r"v\d+$", version or ""):
        return int(version.replace("v", ""))
    return 0


def _next_version(existing_versions: list[str]) -> str:
    max_number = 0

    for version in existing_versions:
        max_number = max(max_number, _version_number(version))

    return f"v{max_number + 1}"


def _default_scenario_session() -> dict:
    return {
        "current_version": None,
        "approved": False,
        "approved_version": None,
        "last_review_version": None,
    }


def _default_testcase_session() -> dict:
    return {
        "current_version": None,
        "approved": False,
        "approved_version": None,
        "last_final_review_version": None,
    }


def _scenario_path(ticket_id: str, version: str) -> Path:
    if version == "approved":
        return _scenario_dir(ticket_id) / "approved_scenarios.json"
    if version == "latest":
        return _scenario_dir(ticket_id) / "scenarios.json"
    return _scenario_dir(ticket_id) / f"scenarios_{version}.json"


def _test_scope_path(ticket_id: str, version: str) -> Path:
    if version == "latest":
        return _scenario_dir(ticket_id) / "test_scope.json"
    return _scenario_dir(ticket_id) / f"test_scope_{version}.json"


def _testcase_path(ticket_id: str, version: str) -> Path:
    if version == "approved":
        return _testcase_dir(ticket_id) / "approved_testcases.json"
    if version == "latest":
        return _testcase_dir(ticket_id) / "testcases.json"
    return _testcase_dir(ticket_id) / f"testcases_{version}.json"


def _load_scenario_session(ticket_id: str) -> dict:
    session = _default_scenario_session()
    session.update(_read_json(_scenario_session_file(ticket_id), {}) or {})
    return session


def _save_scenario_session(ticket_id: str, session: dict) -> str:
    merged = _default_scenario_session()
    merged.update(session or {})
    return _write_json(_scenario_session_file(ticket_id), merged)


def _load_testcase_session(ticket_id: str) -> dict:
    session = _default_testcase_session()
    session.update(_read_json(_testcase_session_file(ticket_id), {}) or {})
    return session


def _save_testcase_session(ticket_id: str, session: dict) -> str:
    merged = _default_testcase_session()
    merged.update(session or {})
    return _write_json(_testcase_session_file(ticket_id), merged)


def _list_versioned_files(directory: Path, prefix: str) -> list[str]:
    if not directory.exists():
        return []

    versions = []
    for file_path in directory.glob(f"{prefix}_v*.json"):
        version = file_path.stem.replace(f"{prefix}_", "")
        if re.match(r"v\d+$", version):
            versions.append(version)

    return versions


def _apply_ai_state(
    state: dict,
    ai_mode: str | None,
    source_channel: str | None,
) -> dict:
    if ai_mode:
        state["ai_mode"] = ai_mode

    if source_channel:
        state["source_channel"] = source_channel

    return state


def prepare_structure_gate(ticket_id: str) -> AppResult:
    return prepare_generation(ticket_id)


def build_generation_state(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> dict:
    return build_structured_generation_state(
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )


def run_structured_generation(
    ticket_id: str,
    generation_state: dict | None = None,
    ai_mode: str | None = None,
    source_channel: str | None = None,
    initialize_review: bool = True,
) -> dict:
    state = generation_state or build_generation_state(
        ticket_id=ticket_id,
        ai_mode=ai_mode,
        source_channel=source_channel,
    )
    state["ticket_id"] = ticket_id
    _apply_ai_state(state, ai_mode, source_channel)

    logger.info(
        "Invoking generation graph source_channel=%s ai_mode=%s ticket_id=%s",
        state.get("source_channel"),
        state.get("ai_mode"),
        ticket_id,
    )

    result = test_generation_graph.invoke(state)

    if initialize_review:
        save_review_session(
            ticket_id,
            {
                "review_iterations": 0,
                "improve_iterations": 0,
                "max_iterations": 3,
                "accepted": False,
            },
        )

    return result


def generate_scope_and_scenarios(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> str:
    approved_structure = load_approved_test_case_structure(ticket_id)
    if not approved_structure:
        raise ValueError("Approved test case structure is required.")

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["approved_test_case_structure"] = approved_structure
    _apply_ai_state(state, ai_mode, source_channel)

    state.update(generate_test_scope(state))
    state.update(generate_scenarios(state))

    scenarios = state.get("scenarios", [])
    test_scope = state.get("test_scope", {})

    if not scenarios:
        raise ValueError("No scenarios generated.")

    version = _next_version(
        _list_versioned_files(_scenario_dir(ticket_id), "scenarios")
    )

    _write_json(_test_scope_path(ticket_id, version), test_scope)
    _write_json(_test_scope_path(ticket_id, "latest"), test_scope)
    _write_json(_scenario_path(ticket_id, version), scenarios)
    _write_json(_scenario_path(ticket_id, "latest"), scenarios)

    _write_json(_root(ticket_id) / "analysis" / "test_scope.json", test_scope)
    _write_json(_root(ticket_id) / "analysis" / "scenarios.json", scenarios)

    session = _load_scenario_session(ticket_id)
    session["current_version"] = version
    session["approved"] = False
    _save_scenario_session(ticket_id, session)

    return version


def generate_testcases_from_approved_scenarios(
    ticket_id: str,
    ai_mode: str | None = None,
    source_channel: str | None = None,
) -> str:
    approved_structure = load_approved_test_case_structure(ticket_id)
    approved_scenarios = _read_json(_scenario_path(ticket_id, "approved"), [])

    if not approved_structure:
        raise ValueError("Approved structure is required.")

    if not approved_scenarios:
        raise ValueError("Approved scenarios are required.")

    state = load_ticket_artifacts(ticket_id)
    state["ticket_id"] = ticket_id
    state["approved_test_case_structure"] = approved_structure
    state["test_scope"] = _read_json(_test_scope_path(ticket_id, "latest"), {})
    state["scenarios"] = approved_scenarios
    _apply_ai_state(state, ai_mode, source_channel)

    result = generate_testcases(state)
    state.update(result)

    testcases = state.get("testcases", [])
    if not testcases:
        raise ValueError("No test cases generated.")

    version = _next_version(
        _list_versioned_files(_testcase_dir(ticket_id), "testcases")
    )

    _write_json(_testcase_path(ticket_id, version), testcases)
    _write_json(_testcase_path(ticket_id, "latest"), testcases)

    session = _load_testcase_session(ticket_id)
    session["current_version"] = version
    session["approved"] = False
    _save_testcase_session(ticket_id, session)

    return version


def export_generated_testcases_excel(
    ticket_id: str,
    result: dict,
    version: str = "latest",
) -> str:
    artifacts = load_ticket_artifacts(ticket_id)

    testcases = (
        result.get("improved_testcases")
        or result.get("testcases")
        or artifacts.get("improved_testcases")
        or artifacts.get("testcases")
        or []
    )

    coverage_review = (
        result.get("coverage_review")
        or artifacts.get("coverage_review")
        or {}
    )

    final_coverage_review = (
        result.get("final_coverage_review")
        or artifacts.get("final_coverage_review")
        or {}
    )

    approved_structure = (
        result.get("approved_test_case_structure")
        or artifacts.get("approved_test_case_structure")
        or {}
    )

    excel_file = export_function_based_testcases_to_excel(
        ticket_id=ticket_id,
        testcases=testcases,
        coverage_review=coverage_review,
        final_coverage_review=final_coverage_review,
        approved_structure=approved_structure,
    )

    if not version:
        return excel_file

    source_file = Path(excel_file)
    versioned_file = (
        source_file.parent
        / f"{ticket_id}_function_based_testcases_{version}.xlsx"
    )

    if source_file.resolve() == versioned_file.resolve():
        return str(source_file)

    shutil.copyfile(source_file, versioned_file)
    return str(versioned_file)
