from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from app.config.env_loader import ENV_FILE_NAMES, PROJECT_ROOT, read_environment_layers
from app.config.environment_schema import (
    DEPRECATED_AI_MODES,
    DEPRECATED_VARIABLES,
    ENUM_VALUES,
    KNOWN_VARIABLES,
    SECRET_VARIABLES,
    VARIABLE_OWNER,
)


def _read_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        str(key): str(value)
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def diagnose_configuration(
    project_root: Path = PROJECT_ROOT,
    process_environment: Mapping[str, str] | None = None,
) -> dict:
    process = dict(os.environ if process_environment is None else process_environment)
    merged, file_sources, found, missing = read_environment_layers(project_root)
    file_values = {name: _read_file(project_root / name) for name in ENV_FILE_NAMES}
    occurrences: dict[str, list[str]] = defaultdict(list)
    for filename, values in file_values.items():
        for key in values:
            occurrences[key].append(filename)

    duplicates = {
        key: files for key, files in sorted(occurrences.items()) if len(files) > 1
    }
    unknown = {
        filename: sorted(key for key in values if key not in KNOWN_VARIABLES)
        for filename, values in file_values.items()
    }
    unknown = {filename: keys for filename, keys in unknown.items() if keys}
    misplaced = {
        filename: sorted(
            key for key in values
            if key in VARIABLE_OWNER and VARIABLE_OWNER[key] != filename
        )
        for filename, values in file_values.items()
    }
    misplaced = {filename: keys for filename, keys in misplaced.items() if keys}

    effective = dict(merged)
    effective.update({key: value for key, value in process.items() if key in KNOWN_VARIABLES})
    effective_sources = {
        key: ("process environment" if key in process else file_sources.get(key, "default/unset"))
        for key in sorted(KNOWN_VARIABLES)
        if key in effective
    }

    invalid_enums = []
    deprecated_ai_modes = []
    for key, allowed in ENUM_VALUES.items():
        if key not in effective:
            continue
        value = effective[key].strip()
        comparison = value.upper() if key.endswith("AI_MODE") else value.lower()
        normalized_allowed = {
            item.upper() if key.endswith("AI_MODE") else item.lower() for item in allowed
        }
        if comparison not in normalized_allowed:
            invalid_enums.append({"variable": key, "value": value, "allowed": sorted(allowed)})
        elif key.endswith("AI_MODE") and comparison in DEPRECATED_AI_MODES:
            deprecated_ai_modes.append({"variable": key, "value": comparison})

    credential_status = {
        key: "configured" if effective.get(key, "").strip() else "not configured"
        for key in sorted(SECRET_VARIABLES)
    }
    credential_sources = {
        key: effective_sources.get(key, "default/unset")
        for key in sorted(SECRET_VARIABLES)
    }
    safe_effective = {
        key: {
            "value": credential_status[key] if key in SECRET_VARIABLES else effective[key],
            "source": effective_sources.get(key, "default/unset"),
        }
        for key in sorted(effective)
        if key in KNOWN_VARIABLES
    }
    qa_modes = {
        key: effective.get(key, "default/unset")
        for key in sorted(KNOWN_VARIABLES)
        if VARIABLE_OWNER.get(key) == ".env.qa"
    }
    ai_modes = {
        key: effective.get(key, "default/unset")
        for key in ("TELEGRAM_AI_MODE", "PORTAL_DEFAULT_AI_MODE", "NON_PORTAL_AI_MODE")
    }
    return {
        "schema_version": "1.0",
        "files": {"found": list(found), "missing": list(missing)},
        "precedence": [*ENV_FILE_NAMES, "process environment"],
        "duplicates": duplicates,
        "unknown_keys": unknown,
        "misplaced_keys": misplaced,
        "deprecated_variables": sorted(key for key in occurrences if key in DEPRECATED_VARIABLES),
        "deprecated_ai_modes": deprecated_ai_modes,
        "invalid_enum_values": invalid_enums,
        "credentials": credential_status,
        "credential_sources": credential_sources,
        "active_qa_rollout": qa_modes,
        "active_ai_routing": ai_modes,
        "effective_configuration": safe_effective,
        "valid": not duplicates and not unknown and not misplaced and not invalid_enums,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect layered configuration without exposing secrets")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true", help="Retained for explicit machine-readable invocation")
    args = parser.parse_args()
    report = diagnose_configuration(Path(args.project_root))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
