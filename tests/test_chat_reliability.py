from pathlib import Path

import pytest

from app.services import chat_service
from app.services.chat_task_router import ChatTaskType, classify_chat_task
from app.services.chat_tools.calculator_tool import answer_calculation_question
from app.services.chat_tools.datetime_tool import answer_datetime_question


@pytest.fixture()
def chat_tmp(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHAT_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    return tmp_path


@pytest.mark.parametrize(
    "message",
    [
        "What day is it today?",
        "What is the time now?",
        "Hôm nay là thứ mấy?",
        "Ngày mai là ngày mấy?",
    ],
)
def test_date_time_classification_for_english_and_vietnamese(message):
    assert classify_chat_task(message) == ChatTaskType.DATE_TIME


@pytest.mark.parametrize(
    "message",
    [
        "2 + 2",
        "Calculate 10 / 2",
        "12 x 3",
        "Tính 7 + 8 bằng bao nhiêu?",
    ],
)
def test_math_calculation_classification(message):
    assert classify_chat_task(message) == ChatTaskType.MATH_CALCULATION


def test_datetime_tool_returns_deterministic_result(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "UTC")

    result = answer_datetime_question("What day is it today?")

    assert result is not None
    assert result.confidence == 1.0
    assert "UTC" in result.answer


def test_calculator_tool_returns_deterministic_result():
    result = answer_calculation_question("Calculate 12 x 3")

    assert result is not None
    assert result.answer == "12 * 3 = 36"


def test_tool_answer_is_saved_with_system_tool_provider(chat_tmp):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="What day is it today?",
        ai_mode="TEST_LOCAL_ONLY",
    )

    messages = chat_service.load_chat_messages(session["session_id"])
    assert result["ok"] is True
    assert result["tool_used"] == "datetime_tool"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["provider"] == "SYSTEM_TOOL"
    assert messages[-1]["model"] == "datetime_tool"


def test_general_chat_still_goes_to_llm(chat_tmp, monkeypatch):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")
    calls = []

    def fake_call_text_llm(**kwargs):
        calls.append(kwargs)
        return "Hello from LLM"

    monkeypatch.setattr(chat_service.llm_router_service, "call_text_llm", fake_call_text_llm)

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="Hello, can you help me think through an idea?",
        ai_mode="TEST_LOCAL_ONLY",
    )

    assert result["ok"] is True
    assert calls
    assert calls[0]["task_type"] == chat_service.llm_router_service.TASK_CHAT


def test_llm_online_lookup_claim_is_guarded_without_tool(chat_tmp, monkeypatch):
    session = chat_service.create_chat_session(ai_mode="TEST_LOCAL_ONLY")

    def fake_call_text_llm(**_kwargs):
        return "I searched online and verified the latest sources."

    monkeypatch.setattr(chat_service.llm_router_service, "call_text_llm", fake_call_text_llm)

    result = chat_service.send_chat_message(
        session_id=session["session_id"],
        user_message="Tell me about testing strategy",
        ai_mode="TEST_LOCAL_ONLY",
    )

    assert result["ok"] is True
    content = result["assistant_message"]["content"]
    assert "should be treated as unverified" in content
