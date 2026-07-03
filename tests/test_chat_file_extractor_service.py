import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.services.chat_file_extractor_service import (
    extract_text_from_file,
    sanitize_upload_filename,
    save_and_extract_uploads,
)


def test_extract_txt_json_and_csv(tmp_path: Path):
    txt_file = tmp_path / "note.txt"
    json_file = tmp_path / "data.json"
    csv_file = tmp_path / "data.csv"

    txt_file.write_text("hello chat", encoding="utf-8")
    json_file.write_text('{"a": 1}', encoding="utf-8")
    csv_file.write_text("name,value\nalpha,1\n", encoding="utf-8")

    assert extract_text_from_file(txt_file) == "hello chat"
    assert '"a": 1' in extract_text_from_file(json_file)
    assert "name, value" in extract_text_from_file(csv_file)


@pytest.mark.asyncio
async def test_unsupported_extension_returns_warning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHAT_SESSIONS_DIR", str(tmp_path))
    upload = UploadFile(
        filename="image.png",
        file=io.BytesIO(b"binary"),
    )

    attachments, context, warnings = await save_and_extract_uploads(
        session_dir=tmp_path / "session",
        files=[upload],
    )

    assert context == ""
    assert warnings == ["Unsupported file type: image.png"]
    assert attachments[0]["warning"] == "Unsupported file type: image.png"


@pytest.mark.asyncio
async def test_uploaded_filename_sanitization_prevents_path_traversal(tmp_path: Path):
    upload = UploadFile(
        filename="../../secret.txt",
        file=io.BytesIO(b"safe text"),
    )

    attachments, context, warnings = await save_and_extract_uploads(
        session_dir=tmp_path / "session",
        files=[upload],
    )

    assert warnings == []
    assert attachments[0]["filename"] == "secret.txt"
    assert "safe text" in context
    assert (tmp_path / "session" / "uploads" / "original" / "secret.txt").exists()
    assert not (tmp_path / "secret.txt").exists()


def test_sanitize_upload_filename_handles_empty_and_unsafe_names():
    assert sanitize_upload_filename("..\\..\\bad name?.txt") == "bad_name_.txt"
    assert sanitize_upload_filename("...") == "upload"
