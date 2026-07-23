from __future__ import annotations

import os
from pathlib import Path

from app.config.env_loader import PROJECT_ROOT, load_project_env


load_project_env()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def knowledge_base_enabled() -> bool:
    return _env_bool("KNOWLEDGE_BASE_ENABLED", False)


def knowledge_base_root() -> Path:
    value = os.getenv("KNOWLEDGE_BASE_ROOT", "knowledge_bases").strip()
    root = Path(value)

    if not root.is_absolute():
        root = PROJECT_ROOT / root

    return root


def maintainer_token() -> str:
    return os.getenv("KNOWLEDGE_BASE_MAINTAINER_TOKEN", "").strip()


def max_upload_size_bytes() -> int:
    return max(_env_int("KNOWLEDGE_BASE_MAX_FILE_SIZE_BYTES", 2 * 1024 * 1024), 1024)


def default_top_k() -> int:
    return max(_env_int("KNOWLEDGE_BASE_DEFAULT_TOP_K", 10), 1)


def package_max_compressed_size_bytes() -> int:
    return max(_env_int("KB_PACKAGE_MAX_COMPRESSED_SIZE_BYTES", 50 * 1024 * 1024), 1024)


def package_max_uncompressed_size_bytes() -> int:
    return max(_env_int("KB_PACKAGE_MAX_UNCOMPRESSED_SIZE_BYTES", 200 * 1024 * 1024), 1024)


def package_max_file_count() -> int:
    return max(_env_int("KB_PACKAGE_MAX_FILE_COUNT", 2000), 1)


def package_max_directory_depth() -> int:
    return max(_env_int("KB_PACKAGE_MAX_DIRECTORY_DEPTH", 12), 2)


def package_max_compression_ratio() -> int:
    return max(_env_int("KB_PACKAGE_MAX_COMPRESSION_RATIO", 100), 1)


def package_allowed_archive_types() -> set[str]:
    raw = os.getenv("KB_PACKAGE_ALLOWED_ARCHIVE_TYPES", "zip")
    return {item.strip().lower().lstrip(".") for item in raw.split(",") if item.strip()}
