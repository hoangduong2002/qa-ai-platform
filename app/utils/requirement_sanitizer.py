import html
import os
import re
from typing import Any

from bs4 import BeautifulSoup


SENSITIVE_TERMS = [
    "Vatech",
    "Weclever",
    "WeClever",
    "WeCleverLink",
    "Ewoosoft",
    "Clever Lab",
    "Ryence",
]

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

URL_PATTERN = re.compile(
    r"https?://[^\s)]+",
    re.IGNORECASE,
)

JIRA_BROWSE_PATTERN = re.compile(
    r"https?://[^/\s]+/browse/([A-Z][A-Z0-9]+-\d+)",
    re.IGNORECASE,
)

JIRA_MENTION_PATTERN = re.compile(
    r"\[~[^\]]+\]"
)

AUTHOR_LINE_PATTERN = re.compile(
    r"^\s*[-*]?\s*(Author|Reporter|Assignee|Creator|Created by|Updated by):\s+.*$",
    re.MULTILINE | re.IGNORECASE,
)

PROFILE_URL_PATTERN = re.compile(
    r"\([^)]*/secure/ViewProfile\.jspa\?name=[^)]+\)",
    re.IGNORECASE,
)

EMAIL_HEADER_PATTERN = re.compile(
    r"^(From|Sent|To|Cc|Subject):\s+.*$",
    re.MULTILINE | re.IGNORECASE,
)

SIGNATURE_START_PATTERN = re.compile(
    r"^\s*(thanks|thank you|best regards|kind regards|regards)\s*[,.!]*\s*$",
    re.IGNORECASE,
)

MULTIPLE_BLANK_LINES_PATTERN = re.compile(
    r"\n{3,}"
)


def _env_bool(
    name: str,
    default: bool = True,
) -> bool:
    value = os.getenv(
        name,
        "true" if default else "false",
    )

    return value.lower() in [
        "1",
        "true",
        "yes",
        "y",
        "on",
    ]


def is_sanitizer_enabled() -> bool:
    return _env_bool(
        "SANITIZE_REQUIREMENT",
        True,
    )


def clean_requirement_text(
    value: Any,
) -> str:
    if not is_sanitizer_enabled():
        return _to_string(value)

    redact_urls = _env_bool("REDACT_URLS", True)
    redact_emails = _env_bool("REDACT_EMAILS", True)
    redact_users = _env_bool("REDACT_USERS", True)
    redact_orgs = _env_bool("REDACT_ORGANIZATIONS", True)

    text = _to_string(value)
    text = html.unescape(text)
    text = _html_to_text(text)
    text = _remove_email_headers(text)
    text = _remove_email_signatures(text)

    text = _redact_pii(
        text=text,
        redact_urls=redact_urls,
        redact_emails=redact_emails,
        redact_users=redact_users,
    )

    if redact_orgs:
        text = _redact_sensitive_terms(text)

    text = _normalize_whitespace(text)

    return text


def _to_string(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    return str(value)


def _looks_like_html(text: str) -> bool:
    return bool(
        re.search(
            r"<\s*(p|div|span|a|img|br|ul|ol|li|table|tr|td|blockquote|pre|code)\b",
            text,
            re.IGNORECASE,
        )
    )


def _html_to_text(text: str) -> str:
    if not _looks_like_html(text):
        return text

    soup = BeautifulSoup(
        text,
        "html.parser",
    )

    for tag in soup(["script", "style"]):
        tag.decompose()

    for img in soup.find_all("img"):
        alt = img.get("alt") or "image"
        img.replace_with(
            f"\n[IMAGE: {alt}]\n"
        )

    for a in soup.find_all("a"):
        label = a.get_text(" ", strip=True)
        href = a.get("href", "")

        if "/secure/ViewProfile.jspa" in href:
            a.replace_with("[USER_REDACTED]")
        elif href:
            jira_key = _extract_jira_key_from_url(href)

            if jira_key:
                a.replace_with(jira_key)
            elif label:
                a.replace_with(label)
            else:
                a.replace_with("[LINK_REDACTED]")
        elif label:
            a.replace_with(label)

    for br in soup.find_all("br"):
        br.replace_with("\n")

    return soup.get_text(
        "\n",
        strip=True,
    )


def _extract_jira_key_from_url(
    url: str,
) -> str:
    match = JIRA_BROWSE_PATTERN.search(url)

    if not match:
        return ""

    return match.group(1).upper()


def _remove_email_headers(
    text: str,
) -> str:
    text = EMAIL_HEADER_PATTERN.sub(
        "",
        text,
    )

    text = re.sub(
        r"-\s*(Author|Reporter|Assignee):\s+.*",
        r"- \1: [USER_REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _remove_email_signatures(
    text: str,
) -> str:
    lines = text.splitlines()
    cleaned = []

    skip_signature = False
    signature_line_count = 0

    for line in lines:
        if SIGNATURE_START_PATTERN.match(line.strip()):
            cleaned.append(line)
            skip_signature = True
            signature_line_count = 0
            continue

        if skip_signature:
            signature_line_count += 1

            if signature_line_count <= 4:
                if (
                    EMAIL_PATTERN.search(line)
                    or "@" in line
                    or "http" in line.lower()
                ):
                    continue

            skip_signature = False

        cleaned.append(line)

    return "\n".join(cleaned)


def _redact_pii(
    text: str,
    redact_urls: bool,
    redact_emails: bool,
    redact_users: bool,
) -> str:
    if redact_users:
        text = JIRA_MENTION_PATTERN.sub(
            "[USER_REDACTED]",
            text,
        )

        text = PROFILE_URL_PATTERN.sub(
            "",
            text,
        )

        def replace_user_metadata_line(match):
            field_name = match.group(1)
            return f"- {field_name}: [USER_REDACTED]"

        text = AUTHOR_LINE_PATTERN.sub(
            replace_user_metadata_line,
            text,
        )

        text = re.sub(
            r"\b(Dear|Hi|Hello)\s+([A-Z][A-Za-zÀ-ỹ'’-]+(?:\s+[A-Z][A-Za-zÀ-ỹ'’-]+){0,3})",
            r"\1 [USER_REDACTED]",
            text,
        )

        text = re.sub(
            r"\bcc\s+([A-Z][A-Za-zÀ-ỹ'’-]+(?:\s+[A-Z][A-Za-zÀ-ỹ'’-]+){0,6})",
            "cc [USER_REDACTED]",
            text,
            flags=re.IGNORECASE,
        )

    if redact_emails:
        text = EMAIL_PATTERN.sub(
            "[EMAIL_REDACTED]",
            text,
        )

    if redact_urls:
        text = URL_PATTERN.sub(
            _replace_url,
            text,
        )

    return text


def _replace_url(
    match,
) -> str:
    url = match.group(0)

    jira_key = _extract_jira_key_from_url(url)

    if jira_key:
        return jira_key

    return "[URL_REDACTED]"


def _redact_sensitive_terms(
    text: str,
) -> str:
    for term in SENSITIVE_TERMS:
        text = re.sub(
            rf"\b{re.escape(term)}\b",
            "[ORG_REDACTED]",
            text,
            flags=re.IGNORECASE,
        )

    return text


def _normalize_whitespace(
    text: str,
) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = MULTIPLE_BLANK_LINES_PATTERN.sub(
        "\n\n",
        text,
    )

    return text.strip()