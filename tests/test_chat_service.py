from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app.services import chat_service


@pytest.fixture()
def chat_tmp(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHAT_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("CHAT_HISTORY_MAX_MESSAGES", "2")
    monkeypatch.setenv("CHAT_MAX_EXTRACTED_CHARS", "12")
    return tmp_path


def test_create_chat_session(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    assert session["session_id"]
    assert session["ai_mode"] == "TEST_LOCAL_ONLY"
    assert (chat_tmp / session["session_id"] / "session.json").exists()
    assert (chat_tmp / session["session_id"] / "messages.jsonl").exists()


def test_create_password_protected_chat_session(chat_tmp):
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        title="Protected",
        password="pass123",
        confirm_password="pass123",
    )
    stored = chat_service.load_chat_session(session["session_id"])

    assert session["password_protected"] is True
    assert "password_hash" not in session
    assert "password_salt" not in session
    assert stored["password_protected"] is True
    assert stored["password_hash"]
    assert stored["password_salt"]


def test_session_json_does_not_contain_plaintext_password(chat_tmp):
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="secret-pass",
        confirm_password="secret-pass",
    )
    session_text = (chat_tmp / session["session_id"] / "session.json").read_text(
        encoding="utf-8",
    )

    assert "secret-pass" not in session_text
    assert "password_hash" in session_text


def test_save_and_load_messages(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    chat_service.append_chat_message(
        session["session_id"],
        {"role": "user", "content": "hello"},
    )

    messages = chat_service.load_chat_messages(session["session_id"])
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"


def test_unlock_with_correct_password_returns_token(chat_tmp):
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="pass123",
        confirm_password="pass123",
    )

    result = chat_service.unlock_chat_session(session["session_id"], "pass123")

    assert result["ok"] is True
    assert result["unlock_token"]
    assert chat_service.is_unlock_token_valid(
        session["session_id"],
        result["unlock_token"],
    )


def test_unlock_with_wrong_password_raises_permission_error(chat_tmp):
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="pass123",
        confirm_password="pass123",
    )

    with pytest.raises(PermissionError, match="Invalid chat password"):
        chat_service.unlock_chat_session(session["session_id"], "wrong")


def test_delete_chat_marks_session_deleted(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    deleted = chat_service.soft_delete_chat_session(session["session_id"])
    stored = chat_service.load_chat_session(session["session_id"])

    assert deleted["deleted"] is True
    assert stored["deleted"] is True
    assert stored["deleted_at"]


def test_deleted_chat_does_not_appear_in_recent_chats(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    chat_service.soft_delete_chat_session(session["session_id"])

    assert chat_service.list_chat_sessions() == []


def test_invalid_session_id_path_traversal_is_rejected(chat_tmp):
    with pytest.raises(ValueError, match="Invalid chat session id"):
        chat_service.load_chat_session("../secret")


def test_prompt_context_truncation(chat_tmp):
    prompt = chat_service.build_chat_prompt(
        current_message="current",
        history=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "middle"},
            {"role": "user", "content": "new"},
        ],
        extracted_context="abcdefghijklmnopqrstuvwxyz",
    )

    assert "old" not in prompt
    assert "middle" in prompt
    assert "abcdefghijkl" in prompt
    assert "abcdefghijklm" not in prompt


def test_no_llm_mode_returns_friendly_error(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="NO_LLM")

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="hello",
        ai_mode="NO_LLM",
    )

    assert result["ok"] is False
    assert result["error"] == chat_service.NO_LLM_CHAT_MESSAGE
    assert chat_service.load_chat_messages(session["session_id"])[0]["content"] == "hello"


def test_chat_response_saves_assistant_message_and_uses_router(chat_tmp, monkeypatch):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")
    calls = []

    def fake_call_text_llm(**kwargs):
        calls.append(kwargs)
        return "assistant response"

    monkeypatch.setattr(chat_service.llm_router_service, "call_text_llm", fake_call_text_llm)

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="help me test",
        ai_mode="TEST_LOCAL_ONLY",
    )

    messages = chat_service.load_chat_messages(session["session_id"])
    assert result["ok"] is True
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "assistant response"
    assert calls[0]["task_type"] == chat_service.llm_router_service.TASK_CHAT
    assert calls[0]["source_channel"] == "web_chat"


def test_provider_failure_returns_friendly_error_and_does_not_crash(chat_tmp, monkeypatch):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    def fail_call_text_llm(**_kwargs):
        raise RuntimeError("Traceback: secret details")

    monkeypatch.setattr(chat_service.llm_router_service, "call_text_llm", fail_call_text_llm)

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="hello",
        ai_mode="TEST_LOCAL_ONLY",
    )

    messages = chat_service.load_chat_messages(session["session_id"])
    assert result["ok"] is False
    assert result["error"] == chat_service.PROVIDER_FAILURE_MESSAGE
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_protected_chat_without_token_returns_password_required(chat_tmp):
    client = TestClient(app)
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="pass123",
        confirm_password="pass123",
    )
    chat_service.append_chat_message(
        session["session_id"],
        {"role": "user", "content": "hidden"},
    )

    response = client.get(f"/portal/chat/sessions/{session['session_id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["password_required"] is True
    assert data["messages"] == []
    assert "password_hash" not in data["session"]


def test_protected_chat_with_valid_token_returns_messages(chat_tmp):
    client = TestClient(app)
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="pass123",
        confirm_password="pass123",
    )
    chat_service.append_chat_message(
        session["session_id"],
        {"role": "user", "content": "visible"},
    )
    unlock = chat_service.unlock_chat_session(session["session_id"], "pass123")

    response = client.get(
        f"/portal/chat/sessions/{session['session_id']}",
        headers={"X-Chat-Unlock-Token": unlock["unlock_token"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["password_required"] is False
    assert data["messages"][0]["content"] == "visible"


def test_unlock_route_with_wrong_password_returns_403(chat_tmp):
    client = TestClient(app)
    session = chat_service.create_chat_session(
        ai_mode="TEST_LOCAL_ONLY",
        password="pass123",
        confirm_password="pass123",
    )

    response = client.post(
        f"/portal/chat/sessions/{session['session_id']}/unlock",
        json={"password": "wrong"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "ok": False,
        "error": "Invalid chat password.",
    }
