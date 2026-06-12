import json
import logging
import os
import re
import shutil
import ssl
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

from atlassian import Jira

logger = logging.getLogger(__name__)

from app.utils.file_extractors import extract_file_text
from app.utils.workspace_writer import create_workspace_from_text
from app.utils.requirement_sanitizer import clean_requirement_text
from app.services.figma_requirement_service import (
    extract_figma_link_records_from_sources,
    extract_figma_context_from_jira_texts,
    extract_figma_references_from_texts,
)
from app.services.requirement_compact_context_service import (
    build_compact_requirement_context,
)
from app.services.local_ai_config_service import (
    is_attachment_local_vision_enabled,
)
from app.services.local_image_extractor_service import extract_image_with_LOCAL


REQUIREMENTS_ROOT = Path("requirements")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VISION_ANALYSIS_SKIPPED_MESSAGE = (
    "Vision analysis skipped because local vision analysis is disabled."
)


def _remove_file_if_exists(file_path: Path) -> None:
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError:
        pass


def _get_jira_token(jira_pat: str = "") -> str:
    return (
        (jira_pat or "").strip()
        or os.getenv("JIRA_PAT", "").strip()
        or os.getenv("JIRA_API_TOKEN", "").strip()
    )


def _is_probably_html(content: bytes) -> bool:
    preview = content[:300].decode("utf-8", errors="ignore").lower()

    return (
        "<html" in preview
        or "<!doctype html" in preview
        or "login.microsoftonline.com" in preview
        or "oauth2" in preview
    )


def _download_binary_with_pat(
    url: str,
    token: str,
    verify_ssl: bool = True,
) -> bytes:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream,*/*",
        "User-Agent": "qa-ai-platform/1.0",
    }

    request = urllib.request.Request(
        url=url,
        headers=headers,
        method="GET",
    )

    context = None

    if not verify_ssl:
        context = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(
            request,
            timeout=120,
            context=context,
        ) as response:
            return response.read()

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"Failed to download Jira attachment. "
            f"HTTP {error.code}. URL={url}. Body={body[:500]}"
        ) from error


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name or "attachment")


def _safe_requirement_id(value: str) -> str:
    value = (value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9._-]+", "-", value)
    value = value.strip("-")

    if not value:
        raise ValueError("Requirement ID is empty.")

    return value


def _is_image_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


JIRA_IMAGE_ANALYSIS_PROMPT = """
You are analyzing a Jira image attachment for QA requirement extraction.

Use only visible image content and provided context.
Do not invent hidden business rules.
Use provided Jira context only to disambiguate the image.

Return concise Markdown with:

# Screen/Image Summary

# Visible UI Text

# UI Elements

# Possible User Actions

# Validation / Error / Success Messages

# QA Notes

# Ambiguities
""".strip()


def _markdown_sections_to_json(markdown: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {}
    current = ""

    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)

        if heading_match:
            current = heading_match.group(1).strip()
            sections.setdefault(current, [])
            continue

        if current and line:
            sections[current].append(line)

    return {
        "sections": {
            heading: "\n".join(lines).strip()
            for heading, lines in sections.items()
        }
    }


def _truncate_text(text: str, max_chars: int = 4000) -> str:
    text = (text or "").strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "\n\n[TRUNCATED]"


def _build_attachment_context(
    ticket_id: str,
    issue_key: str,
    issue: dict,
    comments: list,
    attachment: dict,
    source_location: str,
) -> str:
    fields = issue.get("fields", {}) or {}
    filename = attachment.get("filename", "")
    description = _to_text(fields.get("description"))
    related_comments: list[str] = []

    for index, comment in enumerate(comments or [], start=1):
        comment_text = _to_text(comment.get("body"))

        if not comment_text:
            continue

        author = (
            comment.get("author", {}).get("displayName")
            or comment.get("author", {}).get("name")
            or "Unknown"
        )
        created = comment.get("created", "")
        related_comments.append(
            f"Comment {index} by {author} at {created}:\n{comment_text}"
        )

    lines = [
        "# Jira Attachment Prompt Context",
        "",
        f"- Ticket: {ticket_id}",
        f"- Issue key: {issue_key}",
        f"- Attachment filename: {filename}",
        f"- Attachment mime type: {attachment.get('mimeType', '')}",
        f"- Source location: {source_location}",
        "",
        "## Related Jira Context",
        "",
        "### Issue Summary",
        fields.get("summary") or issue_key,
        "",
        "### Description / Surrounding Text",
        _truncate_text(description, 2000) or "[NO DESCRIPTION]",
        "",
        "### Comments / Surrounding Text",
    ]

    if related_comments:
        lines.append(_truncate_text("\n\n".join(related_comments), 4000))
    else:
        lines.append("[NO COMMENTS]")

    return "\n".join(lines).strip() + "\n"


def _build_jira_vision_prompt(attachment_context: str) -> str:
    return (
        JIRA_IMAGE_ANALYSIS_PROMPT
        + "\n\n# Provided Jira Context\n\n"
        + (attachment_context or "[NO JIRA CONTEXT PROVIDED]").strip()
    )


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _verify_ssl() -> bool:
    return os.getenv("JIRA_VERIFY_SSL", "true").lower() in [
        "1",
        "true",
        "yes",
        "y",
    ]


def _include_subtasks() -> bool:
    return os.getenv("JIRA_INCLUDE_SUBTASKS", "true").lower() in [
        "1",
        "true",
        "yes",
        "y",
    ]


def _get_jira_client(
    jira_pat: str = "",
) -> Jira:
    jira_url = os.getenv("JIRA_SERVER_URL") or os.getenv("JIRA_URL")
    auth_mode = os.getenv("JIRA_AUTH_MODE", "PAT").upper()
    verify_ssl = _verify_ssl()

    if not jira_url:
        raise ValueError("JIRA_SERVER_URL or JIRA_URL is missing in .env")

    jira_url = jira_url.rstrip("/")
    jira_pat = (jira_pat or "").strip()

    if jira_pat:
        return Jira(
            url=jira_url,
            token=jira_pat,
            verify_ssl=verify_ssl,
        )

    if auth_mode == "PAT":
        token = os.getenv("JIRA_PAT") or os.getenv("JIRA_API_TOKEN")

        if not token:
            raise ValueError(
                "Jira PAT is missing. Please enter PAT in Web Portal "
                "or set JIRA_PAT/JIRA_API_TOKEN in .env."
            )

        return Jira(
            url=jira_url,
            token=token,
            verify_ssl=verify_ssl,
        )

    username = os.getenv("JIRA_USERNAME")
    password = os.getenv("JIRA_PASSWORD") or os.getenv("JIRA_API_TOKEN")

    if not username or not password:
        raise ValueError(
            "JIRA_USERNAME and JIRA_PASSWORD/JIRA_API_TOKEN are missing in .env"
        )

    return Jira(
        url=jira_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )


def _to_text(value: Any) -> str:
    return clean_requirement_text(value)


def _raw_jira_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    return json.dumps(
        value,
        ensure_ascii=False,
    )


def _append_raw_figma_source(
    sources: list[dict[str, str]],
    source: str,
    value: Any,
) -> None:
    text = _raw_jira_text(value)

    if not text.strip():
        return

    sources.append(
        {
            "source": source,
            "text": text,
        }
    )


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        )
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_log_file(ticket_id: str, filename: str, content: str) -> None:
    log_file = REQUIREMENTS_ROOT / ticket_id / "logs" / filename
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(content, encoding="utf-8")


def _build_compact_context_safely(ticket_id: str) -> None:
    try:
        result = build_compact_requirement_context(ticket_id)
    except Exception as error:
        error_text = "".join(
            traceback.format_exception(
                type(error),
                error,
                error.__traceback__,
            )
        )
        _write_log_file(
            ticket_id=ticket_id,
            filename="compact_context_error.txt",
            content=error_text,
        )
        print(
            f"[WARN] Compact requirement context build failed for {ticket_id}. "
            f"See requirements/{ticket_id}/logs/compact_context_error.txt"
        )
        return

    print(
        "[INFO] Compact requirement context built. "
        f"ticket_id={ticket_id}, "
        f"path={result.get('compact_context_path', '')}, "
        f"screens={result.get('screen_count', 0)}, "
        f"sections={result.get('section_count', 0)}, "
        f"length={result.get('compact_context_length', 0)}"
    )


def _extract_figma_sources_safely(
    ticket_id: str,
    raw_sources: list[dict[str, str]],
    sanitized_texts: list[str] | None = None,
) -> None:
    figma_enabled = os.getenv("FIGMA_ENABLE_EXTRACTION", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    sanitized_texts = sanitized_texts or []
    raw_link_records = extract_figma_link_records_from_sources(
        raw_sources,
        detected_before_sanitizer=True,
    )
    sanitized_link_records = extract_figma_link_records_from_sources(
        [
            {
                "source": "sanitized",
                "text": text,
            }
            for text in sanitized_texts
        ],
        detected_before_sanitizer=False,
    )
    source_dir = REQUIREMENTS_ROOT / ticket_id / "source"
    figma_links_file = source_dir / "figma_links.json"
    figma_output_path = source_dir / "figma"

    _write_json(
        figma_links_file,
        raw_link_records,
    )

    raw_references = extract_figma_references_from_texts(
        [item.get("text", "") for item in raw_sources]
    )
    detected_summary = [
        {
            "file_key": reference.file_key,
            "node_ids": reference.entry_node_ids,
            "source_link_count": len(reference.source_urls),
        }
        for reference in raw_references
    ]

    print(
        "[INFO] Figma extraction config. "
        f"ticket_id={ticket_id}, "
        f"enabled={figma_enabled}, "
        f"raw_figma_links_detected={len(raw_link_records)}, "
        f"sanitized_figma_links_detected={len(sanitized_link_records)}, "
        f"output_path={figma_output_path}"
    )
    print(
        "[INFO] Figma detected file/node summary. "
        f"ticket_id={ticket_id}, "
        f"items={json.dumps(detected_summary, ensure_ascii=False)}"
    )

    if not figma_enabled:
        print(
            f"[INFO] FIGMA_ENABLE_EXTRACTION=false. "
            f"Skipping Figma extraction for {ticket_id}."
        )
        return

    if not raw_link_records:
        print(
            f"[INFO] No raw Figma links detected before sanitizer for {ticket_id}."
        )
        return

    try:
        context = extract_figma_context_from_jira_texts(
            ticket_id=ticket_id,
            texts=[item.get("text", "") for item in raw_sources],
        )
    except Exception as error:
        error_text = "".join(
            traceback.format_exception(
                type(error),
                error,
                error.__traceback__,
            )
        )
        _write_log_file(
            ticket_id=ticket_id,
            filename="figma_extraction_error.txt",
            content=error_text,
        )
        print(
            f"[WARN] Figma extraction failed for {ticket_id}. "
            f"See requirements/{ticket_id}/logs/figma_extraction_error.txt"
        )
        return

    if context:
        print(f"[INFO] Figma source extraction completed for {ticket_id}.")
    else:
        print(f"[INFO] No Figma source extracted for {ticket_id}.")


def _write_refresh_metadata(
    ticket_id: str,
    issue_key: str,
    refresh_existing: bool,
) -> None:
    requirement_dir = REQUIREMENTS_ROOT / ticket_id
    metadata_file = requirement_dir / "metadata.json"

    metadata = _read_json(metadata_file, {}) or {}

    metadata["ticket_id"] = ticket_id
    metadata["source"] = f"jira:{issue_key}"

    if refresh_existing:
        metadata["source_refreshed_at"] = _utc_now()
        metadata["analysis_stale"] = True
        metadata["structure_stale"] = True
        metadata["scenarios_stale"] = True
        metadata["testcases_stale"] = True
        metadata["stale_reason"] = "Requirement source was refreshed from Jira."
    else:
        metadata.setdefault("created_at", _utc_now())
        metadata["source_loaded_at"] = _utc_now()

    metadata["updated_at"] = _utc_now()

    _write_json(metadata_file, metadata)


def _get_issue_comments(jira: Jira, issue_key: str) -> list:
    try:
        response = jira.issue_get_comments(issue_key)

        if isinstance(response, dict):
            return response.get("comments", []) or []

        if isinstance(response, list):
            return response

        return []

    except Exception:
        return []


def _get_issue_attachments(issue: dict) -> list:
    return (
        issue
        .get("fields", {})
        .get("attachment", [])
        or []
    )


def _get_subtask_keys(issue: dict) -> list[str]:
    subtasks = (
        issue
        .get("fields", {})
        .get("subtasks", [])
        or []
    )

    keys = []

    for subtask in subtasks:
        key = subtask.get("key")

        if key:
            keys.append(key)

    return keys


def _download_attachment(
    jira: Jira,
    attachment: dict,
    output_file: Path,
    jira_pat: str = "",
) -> None:
    content_url = attachment.get("content")

    if not content_url:
        raise ValueError("Attachment content URL is missing.")

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    token = _get_jira_token(jira_pat)

    if not token:
        raise ValueError(
            "Jira PAT is missing when downloading attachment. "
            "Please enter PAT in Web Portal or set JIRA_PAT/JIRA_API_TOKEN."
        )

    content = _download_binary_with_pat(
        url=content_url,
        token=token,
        verify_ssl=_verify_ssl(),
    )

    if _is_probably_html(content):
        preview = content[:800].decode("utf-8", errors="ignore")

        raise ValueError(
            "Downloaded Jira attachment is an HTML login/SSO page, not an image/file. "
            "This means the attachment request was not authenticated correctly. "
            f"filename={attachment.get('filename')} "
            f"url={content_url} "
            f"preview={preview}"
        )

    output_file.write_bytes(content)


def _download_and_extract_attachments(
    jira: Jira,
    ticket_id: str,
    issue_key: str,
    issue: dict,
    comments: list,
    source_location: str,
    jira_pat: str = "",
) -> list[dict]:
    attachments = _get_issue_attachments(issue)

    source_dir = REQUIREMENTS_ROOT / ticket_id / "source"
    attachments_dir = source_dir / "attachments" / issue_key
    extracted_dir = source_dir / "extracted" / issue_key

    attachments_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    extracted_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    extracted_items = []

    for attachment in attachments:
        filename = _safe_filename(
            attachment.get("filename", "attachment")
        )

        attachment_file = attachments_dir / filename

        item = {
            "issue_key": issue_key,
            "filename": filename,
            "path": str(attachment_file),
            "extracted_path": "",
            "attachment_context_path": "",
            "vision_analysis_path": "",
            "vision_analysis_json_path": "",
            "content": "",
            "error": "",
        }

        try:
            _download_attachment(
                jira=jira,
                attachment=attachment,
                output_file=attachment_file,
                jira_pat=jira_pat,
            )

            if _is_image_file(attachment_file):
                attachment_context = _build_attachment_context(
                    ticket_id=ticket_id,
                    issue_key=issue_key,
                    issue=issue,
                    comments=comments,
                    attachment=attachment,
                    source_location=source_location,
                )
                context_file = attachment_file.with_name(
                    f"{attachment_file.stem}_attachment_context.md"
                )
                context_file.write_text(
                    attachment_context,
                    encoding="utf-8",
                )
                item["attachment_context_path"] = str(context_file)

                vision_file = attachment_file.with_name(
                    f"{attachment_file.stem}_vision_analysis.md"
                )
                vision_json_file = attachment_file.with_name(
                    f"{attachment_file.stem}_vision_analysis.json"
                )
                vision_skipped_file = attachment_file.with_name(
                    f"{attachment_file.stem}_vision_analysis_skipped.txt"
                )
                vision_error_file = attachment_file.with_name(
                    f"{attachment_file.stem}_vision_analysis_error.txt"
                )

                if is_attachment_local_vision_enabled():
                    _remove_file_if_exists(vision_skipped_file)
                    _remove_file_if_exists(vision_file)
                    _remove_file_if_exists(vision_json_file)
                    extracted_text = extract_image_with_LOCAL(
                        image_path=attachment_file,
                        prompt=_build_jira_vision_prompt(attachment_context),
                    )
                    vision_file.write_text(
                        extracted_text,
                        encoding="utf-8",
                    )
                    _write_json(
                        vision_json_file,
                        _markdown_sections_to_json(extracted_text),
                    )
                    item["vision_analysis_path"] = str(vision_file)
                    item["vision_analysis_json_path"] = str(vision_json_file)
                    _remove_file_if_exists(vision_error_file)
                else:
                    _remove_file_if_exists(vision_file)
                    _remove_file_if_exists(vision_json_file)
                    _remove_file_if_exists(vision_error_file)
                    vision_skipped_file.write_text(
                        VISION_ANALYSIS_SKIPPED_MESSAGE,
                        encoding="utf-8",
                    )
                    extracted_text = ""
            else:
                extracted_text = extract_file_text(
                    attachment_file,
                )

            extracted_file = extracted_dir / f"{attachment_file.stem}.md"

            extracted_file.write_text(
                extracted_text,
                encoding="utf-8",
            )

            item["extracted_path"] = str(extracted_file)
            item["content"] = extracted_text

        except Exception as error:
            if (
                _is_image_file(attachment_file)
                and attachment_file.exists()
                and is_attachment_local_vision_enabled()
            ):
                _remove_file_if_exists(
                    attachment_file.with_name(
                        f"{attachment_file.stem}_vision_analysis.md"
                    )
                )
                _remove_file_if_exists(
                    attachment_file.with_name(
                        f"{attachment_file.stem}_vision_analysis.json"
                    )
                )
                _remove_file_if_exists(
                    attachment_file.with_name(
                        f"{attachment_file.stem}_vision_analysis_skipped.txt"
                    )
                )
                error_file = attachment_file.with_name(
                    f"{attachment_file.stem}_vision_analysis_error.txt"
                )
                error_file.write_text(
                    "".join(
                        traceback.format_exception(
                            type(error),
                            error,
                            error.__traceback__,
                        )
                    ),
                    encoding="utf-8",
                )
                item["error"] = str(error)
                item["content"] = ""
                item["extracted_path"] = str(error_file)
                extracted_items.append(item)
                continue

            item["error"] = str(error)
            item["content"] = (
                f"Failed to download/extract attachment: {error}"
            )

        extracted_items.append(item)

    return extracted_items


def _format_comments(comments: list) -> str:
    if not comments:
        return "No comments.\n\n"

    content = ""

    for index, comment in enumerate(comments, start=1):
        author = (
            comment.get("author", {}).get("displayName")
            or comment.get("author", {}).get("name")
            or "Unknown"
        )

        created = comment.get("created", "")

        content += f"### Comment {index}\n\n"
        content += f"- Author: {author}\n"
        content += f"- Created: {created}\n\n"
        content += f"{_to_text(comment.get('body'))}\n\n"

    return content


def _format_attachments(
    attachments: list,
    extracted_items: list,
) -> str:
    content = ""

    content += "### Attachment List\n\n"

    if attachments:
        for attachment in attachments:
            content += (
                f"- {attachment.get('filename', '')} "
                f"({attachment.get('mimeType', '')})\n"
            )
    else:
        content += "No attachments.\n"

    content += "\n### Extracted Attachment Content\n\n"

    if extracted_items:
        for item in extracted_items:
            content += f"#### {item['filename']}\n\n"

            if item.get("attachment_context_path"):
                content += (
                    "Attachment context saved: "
                    f"{item['attachment_context_path']}\n\n"
                )

            if item.get("vision_analysis_path"):
                content += (
                    "Vision analysis saved: "
                    f"{item['vision_analysis_path']}\n\n"
                )

            if item.get("error"):
                content += f"Extraction error: {item['error']}\n\n"
            elif item.get("content"):
                content += f"{item.get('content', '')}\n\n"
            else:
                content += "No extracted attachment content.\n\n"
    else:
        content += "No extracted attachment content.\n\n"

    return content


def _build_issue_markdown(
    issue_key: str,
    issue: dict,
    comments: list,
    extracted_items: list,
    section_title: str,
) -> str:
    fields = issue.get("fields", {})

    summary = fields.get("summary") or issue_key
    description = fields.get("description") or ""
    status = (
        fields
        .get("status", {})
        .get("name", "")
    )
    issue_type = (
        fields
        .get("issuetype", {})
        .get("name", "")
    )
    attachments = fields.get("attachment", []) or []

    content = f"## {section_title}: {issue_key}\n\n"
    content += f"### Title\n\n{summary}\n\n"
    content += f"### Issue Type\n\n{issue_type}\n\n"
    content += f"### Status\n\n{status}\n\n"
    content += f"### Description\n\n{_to_text(description)}\n\n"
    content += "### Comments\n\n"
    content += _format_comments(comments)
    content += "### Attachments\n\n"
    content += _format_attachments(
        attachments,
        extracted_items,
    )

    return content


def _write_ticket_snapshot(
    ticket_id: str,
    issue_key: str,
    issue: dict,
    refresh_existing: bool,
) -> None:
    requirement_dir = REQUIREMENTS_ROOT / ticket_id
    ticket_file = requirement_dir / "ticket.json"

    fields = issue.get("fields", {})

    existing = _read_json(ticket_file, {}) or {}

    ticket = {
        **existing,
        "ticket_id": ticket_id,
        "source": "jira",
        "jira_key": issue_key,
        "summary": fields.get("summary") or issue_key,
        "status": (
            fields
            .get("status", {})
            .get("name", "")
        ),
        "issue_type": (
            fields
            .get("issuetype", {})
            .get("name", "")
        ),
        "updated_at": _utc_now(),
    }

    if not existing:
        ticket["created_at"] = _utc_now()

    if refresh_existing:
        ticket["source_refreshed_at"] = _utc_now()

    _write_json(ticket_file, ticket)


def _requirement_is_complete(ticket_id: str) -> bool:
    """Check whether a requirement has been fully loaded (source + ticket.json).

    Does NOT require sanitized_requirement.md — that check belongs to the
    higher-level requirement_is_complete() in web_requirement_service.
    This lower-level check only verifies the Jira source is loaded.
    """
    requirement_dir = REQUIREMENTS_ROOT / ticket_id
    if not requirement_dir.exists():
        return False

    ticket_file = requirement_dir / "ticket.json"
    if not ticket_file.exists():
        return False

    source_dir = requirement_dir / "source"
    has_jira_md = (source_dir / "jira_requirement.md").exists()
    has_description_md = (source_dir / "description.md").exists()

    return has_jira_md or has_description_md


def _prepare_source_directory(
    ticket_id: str,
    refresh_existing: bool,
) -> tuple[Path, Path]:
    requirement_dir = REQUIREMENTS_ROOT / ticket_id
    source_dir = requirement_dir / "source"
    jira_dir = source_dir / "jira"

    if requirement_dir.exists() and refresh_existing:
        if source_dir.exists():
            shutil.rmtree(source_dir)

    jira_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return source_dir, jira_dir


def create_requirement_from_jira(
    issue_key: str,
    jira_pat: str = "",
    refresh_existing: bool = False,
) -> str:
    issue_key = issue_key.strip().upper()
    ticket_id = _safe_requirement_id(issue_key)

    requirement_dir = REQUIREMENTS_ROOT / ticket_id

    if _requirement_is_complete(ticket_id) and not refresh_existing:
        logger.info(
            "Requirement source exists and is complete, skipping Jira load. ticket_id=%s",
            ticket_id,
        )
        return ticket_id

    if requirement_dir.exists() and not _requirement_is_complete(ticket_id):
        logger.warning(
            "Requirement folder exists but source is incomplete, rebuilding. ticket_id=%s",
            ticket_id,
        )
        refresh_existing = True

    jira = _get_jira_client(
        jira_pat=jira_pat,
    )

    _, jira_dir = _prepare_source_directory(
        ticket_id=ticket_id,
        refresh_existing=refresh_existing,
    )

    main_issue = jira.issue(
        issue_key,
        fields="summary,description,comment,attachment,subtasks,status,issuetype",
    )

    raw_issue_file = jira_dir / f"{issue_key}_raw.json"

    raw_issue_file.write_text(
        json.dumps(
            main_issue,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    main_comments = _get_issue_comments(
        jira,
        issue_key,
    )
    raw_figma_sources: list[dict[str, str]] = []
    _append_raw_figma_source(
        raw_figma_sources,
        "description",
        main_issue.get("fields", {}).get("description"),
    )

    for index, comment in enumerate(main_comments, start=1):
        _append_raw_figma_source(
            raw_figma_sources,
            f"comment:{issue_key}:{index}",
            comment.get("body"),
        )

    main_extracted_items = _download_and_extract_attachments(
        jira=jira,
        ticket_id=ticket_id,
        issue_key=issue_key,
        issue=main_issue,
        comments=main_comments,
        source_location="main issue attachment; related description/comments",
        jira_pat=jira_pat,
    )

    markdown = f"# Jira Requirement: {issue_key}\n\n"

    markdown += _build_issue_markdown(
        issue_key=issue_key,
        issue=main_issue,
        comments=main_comments,
        extracted_items=main_extracted_items,
        section_title="Main Ticket",
    )

    if _include_subtasks():
        subtask_keys = _get_subtask_keys(main_issue)

        markdown += "\n# Subtasks\n\n"

        if not subtask_keys:
            markdown += "No subtasks.\n\n"

        for subtask_key in subtask_keys:
            try:
                sub_issue = jira.issue(
                    subtask_key,
                    fields="summary,description,comment,attachment,subtasks,status,issuetype",
                )

                sub_raw_file = jira_dir / f"{subtask_key}_raw.json"

                sub_raw_file.write_text(
                    json.dumps(
                        sub_issue,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                sub_comments = _get_issue_comments(
                    jira,
                    subtask_key,
                )
                _append_raw_figma_source(
                    raw_figma_sources,
                    f"subtask:{subtask_key}:description",
                    sub_issue.get("fields", {}).get("description"),
                )

                for index, comment in enumerate(sub_comments, start=1):
                    _append_raw_figma_source(
                        raw_figma_sources,
                        f"subtask:{subtask_key}:comment:{index}",
                        comment.get("body"),
                    )

                sub_extracted_items = _download_and_extract_attachments(
                    jira=jira,
                    ticket_id=ticket_id,
                    issue_key=subtask_key,
                    issue=sub_issue,
                    comments=sub_comments,
                    source_location="subtask attachment; related subtask description/comments",
                    jira_pat=jira_pat,
                )

                markdown += _build_issue_markdown(
                    issue_key=subtask_key,
                    issue=sub_issue,
                    comments=sub_comments,
                    extracted_items=sub_extracted_items,
                    section_title="Subtask",
                )

            except Exception as error:
                markdown += (
                    f"## Subtask: {subtask_key}\n\n"
                    f"Failed to fetch subtask: {error}\n\n"
                )
    else:
        markdown += "\n# Subtasks\n\nSubtask loading is disabled.\n\n"

    raw_markdown_file = jira_dir / f"{issue_key}_raw.md"
    markdown_file = jira_dir / f"{issue_key}.md"

    raw_markdown_file.write_text(
        markdown,
        encoding="utf-8",
    )

    markdown_file.write_text(
        markdown,
        encoding="utf-8",
    )

    create_workspace_from_text(
        ticket_id,
        markdown,
        source=f"jira:{issue_key}",
    )

    source_dir = REQUIREMENTS_ROOT / ticket_id / "source"
    jira_requirement_file = source_dir / "jira_requirement.md"
    jira_requirement_file.write_text(
        markdown,
        encoding="utf-8",
    )

    _extract_figma_sources_safely(
        ticket_id=ticket_id,
        raw_sources=raw_figma_sources,
        sanitized_texts=[markdown],
    )

    _build_compact_context_safely(ticket_id)

    _write_ticket_snapshot(
        ticket_id=ticket_id,
        issue_key=issue_key,
        issue=main_issue,
        refresh_existing=refresh_existing,
    )

    _write_refresh_metadata(
        ticket_id=ticket_id,
        issue_key=issue_key,
        refresh_existing=refresh_existing,
    )

    return ticket_id
