import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config.env_loader import PROJECT_ROOT, load_project_env


load_project_env()

DEFAULT_LINK_TARGET = "_blank"
DEFAULT_CONFIG_PATH = "config/knowledge_projects.json"
ALLOWED_LINK_TARGETS = {"_blank", "_self", "_parent", "_top"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_link_target(value: Any) -> str | None:
    target = str(value or "").strip().lower()
    return target if target in ALLOWED_LINK_TARGETS else None


def _resolve_config_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_json_text(raw_value: str, source_label: str) -> tuple[Any, list[str]]:
    try:
        return json.loads(raw_value), []
    except (TypeError, json.JSONDecodeError) as error:
        return None, [f"Could not parse {source_label}: {error}"]


def _load_raw_projects() -> tuple[Any, list[str]]:
    config_path_value = os.getenv("KNOWLEDGE_SYSTEM_CONFIG_PATH", "").strip()
    fallback_json = os.getenv("KNOWLEDGE_SYSTEM_PROJECTS_JSON", "").strip()
    warnings: list[str] = []

    if not config_path_value and fallback_json:
        projects, parse_warnings = _load_json_text(
            fallback_json,
            "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        )
        return projects, parse_warnings

    config_path_value = config_path_value or DEFAULT_CONFIG_PATH

    if config_path_value:
        config_path = _resolve_config_path(config_path_value)

        if config_path.is_file():
            try:
                raw_value = config_path.read_text(encoding="utf-8")
            except OSError as error:
                warnings.append(
                    f"Could not read Knowledge System config file {config_path}: {error}"
                )
            else:
                projects, parse_warnings = _load_json_text(
                    raw_value,
                    f"Knowledge System config file {config_path}",
                )
                warnings.extend(parse_warnings)

                if not parse_warnings:
                    return projects, warnings
        else:
            warnings.append(
                f"Knowledge System config file was not found: {config_path}"
            )

    if fallback_json:
        projects, parse_warnings = _load_json_text(
            fallback_json,
            "KNOWLEDGE_SYSTEM_PROJECTS_JSON",
        )
        warnings.extend(parse_warnings)
        return projects, warnings

    return [], warnings


def _validate_url(value: Any, allow_http: bool) -> tuple[str | None, str]:
    url = str(value or "").strip()

    if not url:
        return None, "URL is required"

    try:
        parsed = urlparse(url)
    except ValueError:
        return None, "URL could not be parsed"

    scheme = parsed.scheme.lower()

    if scheme == "https" and parsed.netloc:
        return url, ""

    if scheme == "http" and parsed.netloc:
        if allow_http:
            return url, ""
        return None, "HTTP links require KNOWLEDGE_SYSTEM_ALLOW_HTTP=true"

    return None, "only valid HTTPS links are allowed"


def _link_type(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host in {"chatgpt.com", "www.chatgpt.com"} and parsed.path.startswith("/g/"):
        return "ChatGPT GPT"

    return host or "External knowledge system"


def _validate_projects(
    raw_projects: Any,
    *,
    default_target: str,
    allow_http: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_projects, list):
        return [], ["Knowledge System project configuration must be a JSON array."]

    projects: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, raw_project in enumerate(raw_projects, start=1):
        label = f"Knowledge project #{index}"

        if not isinstance(raw_project, dict):
            warnings.append(f"{label} must be a JSON object and was skipped.")
            continue

        if raw_project.get("enabled", True) is False:
            continue

        key = str(raw_project.get("key") or "").strip()
        name = str(raw_project.get("name") or "").strip()

        if not key:
            warnings.append(f"{label} is missing required field 'key' and was skipped.")
            continue

        label = f"Knowledge project '{key}'"

        if not name:
            warnings.append(f"{label} is missing required field 'name' and was skipped.")
            continue

        url, url_error = _validate_url(raw_project.get("url"), allow_http)

        if not url:
            warnings.append(f"{label} has an invalid URL ({url_error}) and was skipped.")
            continue

        project_target_value = raw_project.get("target")
        target = _resolve_link_target(project_target_value) if project_target_value else default_target

        if project_target_value and target is None:
            warnings.append(
                f"{label} has an invalid link target; using {default_target}."
            )
            target = default_target

        raw_tags = raw_project.get("tags", [])
        tags = (
            [str(tag).strip() for tag in raw_tags if str(tag).strip()]
            if isinstance(raw_tags, list)
            else []
        )

        if raw_tags and not isinstance(raw_tags, list):
            warnings.append(f"{label} tags must be an array and were ignored.")

        projects.append(
            {
                "key": key,
                "name": name,
                "description": str(raw_project.get("description") or "").strip(),
                "url": url,
                "target": target,
                "rel": "noopener noreferrer" if target == "_blank" else "",
                "tags": tags,
                "link_type": _link_type(url),
            }
        )

    return projects, warnings


def load_knowledge_system() -> dict[str, Any]:
    enabled = _env_bool("KNOWLEDGE_SYSTEM_ENABLED", True)
    configured_target = os.getenv(
        "KNOWLEDGE_SYSTEM_LINK_TARGET",
        DEFAULT_LINK_TARGET,
    )
    link_target = _resolve_link_target(configured_target)
    warnings: list[str] = []

    if link_target is None:
        link_target = DEFAULT_LINK_TARGET
        warnings.append(
            "KNOWLEDGE_SYSTEM_LINK_TARGET is invalid; using _blank."
        )

    if not enabled:
        return {
            "enabled": False,
            "link_target": link_target,
            "projects": [],
            "warnings": warnings,
        }

    raw_projects, load_warnings = _load_raw_projects()
    projects, validation_warnings = _validate_projects(
        raw_projects,
        default_target=link_target,
        allow_http=_env_bool("KNOWLEDGE_SYSTEM_ALLOW_HTTP", False),
    )

    return {
        "enabled": True,
        "link_target": link_target,
        "projects": projects,
        "warnings": [*warnings, *load_warnings, *validation_warnings],
    }
