import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from atlassian import Jira

from app.utils.file_extractors import extract_file_text
from app.utils.workspace_writer import create_workspace_from_text
from app.utils.requirement_sanitizer import clean_requirement_text


REQUIREMENTS_ROOT = Path("requirements")


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name or "attachment")


def _safe_requirement_id(value: str) -> str:
    value = (value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9._-]+", "-", value)
    value = value.strip("-")

    if not value:
        raise ValueError("Requirement ID is empty.")

    return value


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
) -> None:
    content_url = attachment.get("content")

    if not content_url:
        raise ValueError("Attachment content URL is missing.")

    response = jira.get(
        content_url,
        not_json_response=True,
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_file.open("wb") as file:
        if isinstance(response, bytes):
            file.write(response)
        elif hasattr(response, "content"):
            file.write(response.content)
        else:
            file.write(bytes(response))


def _download_and_extract_attachments(
    jira: Jira,
    ticket_id: str,
    issue_key: str,
    issue: dict,
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
            "content": "",
            "error": "",
        }

        try:
            _download_attachment(
                jira=jira,
                attachment=attachment,
                output_file=attachment_file,
            )

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

            if item.get("error"):
                content += f"Extraction error: {item['error']}\n\n"
            else:
                content += f"{item.get('content', '')}\n\n"
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

    if requirement_dir.exists() and not refresh_existing:
        return ticket_id

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

    main_extracted_items = _download_and_extract_attachments(
        jira=jira,
        ticket_id=ticket_id,
        issue_key=issue_key,
        issue=main_issue,
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

                sub_extracted_items = _download_and_extract_attachments(
                    jira=jira,
                    ticket_id=ticket_id,
                    issue_key=subtask_key,
                    issue=sub_issue,
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