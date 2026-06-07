import json
from pathlib import Path
from typing import Any


def get_testcases_dir(ticket_id: str) -> Path:
    return Path("requirements") / ticket_id / "testcases"


def get_function_testcases_dir(ticket_id: str) -> Path:
    return get_testcases_dir(ticket_id) / "functions"


def get_function_testcase_file(ticket_id: str, function_id: str) -> Path:
    return get_function_testcases_dir(ticket_id) / f"{function_id}.json"


def get_function_generation_manifest_file(ticket_id: str) -> Path:
    return get_testcases_dir(ticket_id) / "function_generation_manifest.json"


def save_json(file_path: Path, data: Any) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(file_path)


def save_function_testcases(
    ticket_id: str,
    function_id: str,
    testcases: list,
) -> str:
    return save_json(
        get_function_testcase_file(ticket_id, function_id),
        testcases,
    )


def save_function_generation_manifest(
    ticket_id: str,
    manifest: dict,
) -> str:
    return save_json(
        get_function_generation_manifest_file(ticket_id),
        manifest,
    )