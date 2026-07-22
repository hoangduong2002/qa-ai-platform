from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_NAMES = (".env", ".env.ai", ".env.qa", ".env.secrets")


@dataclass(frozen=True)
class EnvironmentLoadResult:
    project_root: Path
    found_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    file_sources: dict[str, str]
    process_override_keys: tuple[str, ...]


def read_environment_layers(project_root: Path = PROJECT_ROOT) -> tuple[dict[str, str], dict[str, str], tuple[str, ...], tuple[str, ...]]:
    """Read and merge layers without mutating the process environment."""
    merged: dict[str, str] = {}
    sources: dict[str, str] = {}
    found: list[str] = []
    missing: list[str] = []

    for filename in ENV_FILE_NAMES:
        path = project_root / filename
        if not path.exists():
            missing.append(filename)
            continue
        found.append(filename)
        for key, value in dotenv_values(path, interpolate=False).items():
            if value is None:
                continue
            merged[str(key)] = str(value)
            sources[str(key)] = filename

    return merged, sources, tuple(found), tuple(missing)


def load_project_env(
    project_root: Path = PROJECT_ROOT,
    environ: MutableMapping[str, str] | None = None,
) -> EnvironmentLoadResult:
    """Load layered project configuration while preserving process priority.

    File precedence, from lowest to highest, is .env, .env.ai, .env.qa,
    .env.secrets. Existing process variables are never overwritten.
    All files are optional so NO_LLM and rule-based commands can run cleanly.
    """
    target = os.environ if environ is None else environ
    merged, sources, found, missing = read_environment_layers(project_root)
    process_overrides = tuple(sorted(key for key in merged if key in target))
    for key, value in merged.items():
        target.setdefault(key, value)
    return EnvironmentLoadResult(
        project_root=project_root,
        found_files=found,
        missing_files=missing,
        file_sources=sources,
        process_override_keys=process_overrides,
    )
