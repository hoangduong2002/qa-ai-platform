import json
import os
import re
from pathlib import Path
from typing import Any

from atlassian import Jira

from app.utils.file_extractors import extract_file_text
from app.utils.workspace_writer import create_workspace_from_text


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name or "attachment")


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


def _get_jira_client() -> Jira:
    jira_url = os.getenv("JIRA_SERVER_URL") or os.getenv("JIRA_URL")
    auth_mode = os.getenv("JIRA_AUTH_MODE", "PAT").upper()
    verify_ssl = _verify_ssl()

    if not jira_url:
        raise ValueError("JIRA_SERVER_URL or JIRA_URL is missing in .env")

    jira_url = jira_url.rstrip("/")

    if auth_mode == "PAT":
        token = os.getenv("JIRA_PAT") or os.getenv("JIRA_API_TOKEN")

        if not token:
            raise ValueError("JIRA_PAT or JIRA_API_TOKEN is missing in .env")

        return Jira(
            url=jira_url,
            token=token,
            verify_ssl=verify_ssl,
        )

    username = os.getenv("JIRA_USERNAME")
    password = os.getenv("JIRA_PASSWORD") or os.getenv("JIRA_API_TOKEN")

    if not username or not password:
        raise ValueError("JIRA_USERNAME and JIRA_PASSWORD/JIRA_API_TOKEN are missing in .env")

    return Jira(
        url=jira_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )


def _to_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    return json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
    )


def _get_issue_comments(jira: Jira, issue_key: str) -> list:
    try:
        response = jira.issue_get_comments(issue_key)

        if isinstance(response, dict):
            return response.get("comments", [])

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
        file.write(response.content)


def _download_and_extract_attachments(
    jira: Jira,
    ticket_id: str,
    issue_key: str,
    issue: dict,
) -> list[dict]:
    attachments = _get_issue_attachments(issue)

    source_dir = Path("requirements") / ticket_id / "source"
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


def create_requirement_from_jira(
    issue_key: str,
) -> str:
    issue_key = issue_key.strip().upper()

    jira = _get_jira_client()

    ticket_id = issue_key

    source_dir = Path("requirements") / ticket_id / "source"
    jira_dir = source_dir / "jira"

    jira_dir.mkdir(
        parents=True,
        exist_ok=True,
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

    requirement_file = jira_dir / f"{issue_key}.md"

    requirement_file.write_text(
        markdown,
        encoding="utf-8",
    )

    create_workspace_from_text(
        ticket_id,
        markdown,
        source=f"jira:{issue_key}",
    )

    return ticket_id