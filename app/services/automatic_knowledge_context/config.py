from __future__ import annotations

import os


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default)).strip()), minimum)
    except (TypeError, ValueError):
        return default


def max_queries() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERIES", 5)


def top_k_per_query() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_TOP_K", 5)


def max_retrieved_references() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_MAX_RESULTS", 30)


def max_selected_references() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_MAX_SELECTED", 10)


def max_context_characters() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_MAX_CONTEXT_CHARS", 12000, 1000)


def max_query_characters() -> int:
    return _env_int("KNOWLEDGE_AUTO_RETRIEVAL_MAX_QUERY_CHARS", 500, 50)


def minimum_score() -> float | None:
    raw = os.getenv("KNOWLEDGE_AUTO_RETRIEVAL_MIN_SCORE", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
