from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|jira_pat)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_URL_CREDENTIAL = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)


def redact_text(value: str, *, max_length: int = 1000) -> str:
    clean = _EMAIL.sub("[REDACTED_EMAIL]", str(value or ""))
    clean = _BEARER.sub("Bearer [REDACTED]", clean)
    clean = _URL_CREDENTIAL.sub("https://[REDACTED]@", clean)
    return clean[:max_length]


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value, max_length=20000)
    return value

