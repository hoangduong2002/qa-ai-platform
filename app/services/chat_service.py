import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services import llm_router_service
from app.services.ai_mode_context_service import normalize_ai_mode
from app.services.chat_task_router import ChatTaskType, classify_chat_task
from app.services.chat_tools.calculator_tool import answer_calculation_question
from app.services.chat_tools.datetime_tool import answer_datetime_question


CHAT_SYSTEM_PROMPT = (
    "You are an AI assistant inside QA AI Platform. Help the user analyze QA, "
    "requirements, test cases, automation, security, performance, and general "
    "software testing topics. Answer clearly and safely. You do not have "
    "internet browsing unless explicit tool results are provided. Do not claim "
    "online lookup, source checking, or live verification unless a tool result "
    "is included. For exact calculations, dates, and times, rely on provided "
    "tool results. If something is uncertain or not verified, say so clearly."
)
NO_LLM_CHAT_MESSAGE = "NO_LLM mode is selected. Please choose an AI mode to chat."
PROVIDER_FAILURE_MESSAGE = (
    "The AI provider could not complete this chat response. Please check the "
    "selected AI mode and provider configuration, then try again."
)
INVALID_PASSWORD_MESSAGE = "Invalid chat password."
CHAT_SESSION_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")
PASSWORD_HASH_ITERATIONS = 200000
ONLINE_CLAIM_GUARD_MESSAGE = (
    "\n\nNote: I do not have internet browsing in this chat unless an explicit "
    "tool result is provided, so any live online/source-checking claim above "
    "should be treated as unverified."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def get_chat_sessions_dir() -> Path:
    return Path(os.getenv("CHAT_SESSIONS_DIR", "runtime/chat_sessions"))


def get_history_max_messages() -> int:
    return max(_env_int("CHAT_HISTORY_MAX_MESSAGES", 10), 0)


def get_context_max_chars() -> int:
    return max(_env_int("CHAT_MAX_EXTRACTED_CHARS", 60000), 1)


def get_unlock_token_ttl_hours() -> int:
    return max(_env_int("CHAT_UNLOCK_TOKEN_TTL_HOURS", 8), 1)


def _session_dir(session_id: str) -> Path:
    if not session_id or not CHAT_SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid chat session id.")

    return get_chat_sessions_dir() / session_id


def create_chat_session(
    ai_mode: str | None = None,
    title: str | None = None,
    password: str = "",
    confirm_password: str = "",
) -> dict[str, Any]:
    session_id = uuid4().hex
    now = _now()
    resolved_ai_mode = normalize_ai_mode(ai_mode or os.getenv("PORTAL_DEFAULT_AI_MODE") or "NO_LLM")
    clean_title = (title or "").strip() or "New Chat"
    session = {
        "session_id": session_id,
        "title": clean_title[:120],
        "created_at": now,
        "updated_at": now,
        "ai_mode": resolved_ai_mode,
        "password_protected": False,
        "deleted": False,
    }

    password = password or ""
    confirm_password = confirm_password or ""
    if password:
        if password != confirm_password:
            raise ValueError("Chat passwords do not match.")
        if len(password) < 4:
            raise ValueError("Chat password must be at least 4 characters.")
        password_salt = secrets.token_bytes(16)
        session["password_protected"] = True
        session["password_salt"] = password_salt.hex()
        session["password_hash"] = _hash_password(password, password_salt)

    session_dir = _session_dir(session_id)
    (session_dir / "uploads" / "original").mkdir(parents=True, exist_ok=True)
    (session_dir / "uploads" / "extracted").mkdir(parents=True, exist_ok=True)
    _write_json(session_dir / "session.json", session)
    (session_dir / "messages.jsonl").touch(exist_ok=True)

    return public_chat_session(session)


def list_chat_sessions(limit: int = 30) -> list[dict[str, Any]]:
    root = get_chat_sessions_dir()
    if not root.exists():
        return []

    sessions = []
    for session_file in root.glob("*/session.json"):
        try:
            session = _read_json(session_file)
            if session.get("deleted"):
                continue
            sessions.append(public_chat_session(session))
        except (OSError, json.JSONDecodeError):
            continue

    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return sessions[:limit]


def load_chat_session(session_id: str) -> dict[str, Any]:
    session_file = _session_dir(session_id) / "session.json"
    if not session_file.exists():
        raise FileNotFoundError("Chat session not found.")

    return _read_json(session_file)


def public_chat_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in session.items()
        if key not in {"password_hash", "password_salt"}
    }


def is_chat_deleted(session_id: str) -> bool:
    return bool(load_chat_session(session_id).get("deleted"))


def load_chat_messages(session_id: str) -> list[dict[str, Any]]:
    messages_file = _session_dir(session_id) / "messages.jsonl"
    if not messages_file.exists():
        return []

    messages = []
    with messages_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                messages.append(json.loads(line))

    return messages


def soft_delete_chat_session(session_id: str) -> dict[str, Any]:
    session_file = _session_dir(session_id) / "session.json"
    if not session_file.exists():
        raise FileNotFoundError("Chat session not found.")

    session = _read_json(session_file)
    session["deleted"] = True
    session["deleted_at"] = _now()
    session["updated_at"] = _now()
    _write_json(session_file, session)
    return public_chat_session(session)


def unlock_chat_session(session_id: str, password: str) -> dict[str, Any]:
    session = load_chat_session(session_id)

    if session.get("deleted"):
        raise FileNotFoundError("Chat session not found.")

    if not session.get("password_protected"):
        return {"ok": True, "unlock_token": ""}

    if not verify_chat_password(session, password or ""):
        raise PermissionError(INVALID_PASSWORD_MESSAGE)

    token = secrets.token_urlsafe(32)
    token_hash = _hash_unlock_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=get_unlock_token_ttl_hours())
    token_file = _session_dir(session_id) / "unlock_tokens.json"
    tokens = _load_unlock_tokens(token_file)
    tokens = [
        item
        for item in tokens
        if _parse_datetime(item.get("expires_at")) > datetime.now(timezone.utc)
    ]
    tokens.append(
        {
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "created_at": _now(),
        }
    )
    token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    return {"ok": True, "unlock_token": token}


def is_unlock_token_valid(session_id: str, unlock_token: str | None) -> bool:
    if not unlock_token:
        return False

    token_file = _session_dir(session_id) / "unlock_tokens.json"
    tokens = _load_unlock_tokens(token_file)
    now = datetime.now(timezone.utc)
    token_hash = _hash_unlock_token(unlock_token)

    return any(
        hmac.compare_digest(str(item.get("token_hash") or ""), token_hash)
        and _parse_datetime(item.get("expires_at")) > now
        for item in tokens
    )


def verify_chat_password(session: dict[str, Any], password: str) -> bool:
    salt_hex = str(session.get("password_salt") or "")
    expected_hash = str(session.get("password_hash") or "")
    if not salt_hex or not expected_hash:
        return False

    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False

    actual_hash = _hash_password(password, salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def append_chat_message(session_id: str, message: dict[str, Any]) -> dict[str, Any]:
    session_dir = _session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "message_id": message.get("message_id") or uuid4().hex,
        "role": message.get("role", "user"),
        "content": message.get("content", ""),
        "attachments": message.get("attachments", []),
        "provider": message.get("provider", ""),
        "model": message.get("model", ""),
        "duration_ms": int(message.get("duration_ms") or 0),
        "created_at": message.get("created_at") or _now(),
    }

    with (session_dir / "messages.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    _touch_session(session_id)
    return record


def send_chat_message(
    session_id: str,
    user_message: str,
    ai_mode: str,
    attachments: list[dict[str, Any]] | None = None,
    extracted_context: str = "",
) -> dict[str, Any]:
    session = load_chat_session(session_id)
    resolved_ai_mode = normalize_ai_mode(ai_mode or session.get("ai_mode") or "NO_LLM")
    clean_message = (user_message or "").strip()

    if not clean_message and not extracted_context:
        raise ValueError("Enter a message or upload a supported file.")

    user_record = append_chat_message(
        session_id,
        {
            "role": "user",
            "content": clean_message,
            "attachments": attachments or [],
        },
    )
    _update_session_title_and_mode(session_id, clean_message, resolved_ai_mode)

    if resolved_ai_mode == "NO_LLM":
        return {
            "ok": False,
            "error": NO_LLM_CHAT_MESSAGE,
            "user_message": user_record,
            "assistant_message": None,
        }

    task_type = classify_chat_task(
        clean_message,
        has_file_context=bool(extracted_context.strip()),
    )
    tool_result = _answer_with_deterministic_tool(task_type, clean_message)
    if tool_result:
        assistant_record = append_chat_message(
            session_id,
            {
                "role": "assistant",
                "content": tool_result["answer"],
                "provider": "SYSTEM_TOOL",
                "model": tool_result["tool_name"],
                "duration_ms": 0,
            },
        )

        return {
            "ok": True,
            "error": "",
            "user_message": user_record,
            "assistant_message": assistant_record,
            "task_type": task_type.value,
            "tool_used": tool_result["tool_name"],
        }

    prompt = build_chat_prompt(
        current_message=clean_message,
        history=load_chat_messages(session_id)[:-1],
        extracted_context=extracted_context,
    )
    started = time.time()

    try:
        response = llm_router_service.call_text_llm(
            task_type=llm_router_service.TASK_CHAT,
            prompt=prompt,
            system_prompt=CHAT_SYSTEM_PROMPT,
            ai_mode=resolved_ai_mode,
            source_channel="web_chat",
            ticket_id="",
            node_name="chat",
        )
    except Exception:
        return {
            "ok": False,
            "error": PROVIDER_FAILURE_MESSAGE,
            "user_message": user_record,
            "assistant_message": None,
        }

    response = guard_chat_response(response, tool_used=False)
    assistant_record = append_chat_message(
        session_id,
        {
            "role": "assistant",
            "content": response,
            "duration_ms": int((time.time() - started) * 1000),
        },
    )

    return {
        "ok": True,
        "error": "",
        "user_message": user_record,
        "assistant_message": assistant_record,
        "task_type": task_type.value,
        "tool_used": "",
    }


def build_chat_prompt(
    current_message: str,
    history: list[dict[str, Any]],
    extracted_context: str = "",
) -> str:
    recent_history = history[-get_history_max_messages():]
    parts = []

    if recent_history:
        parts.append("Recent conversation:")
        for message in recent_history:
            role = str(message.get("role") or "user").lower()
            if role not in {"user", "assistant", "system"}:
                role = "user"
            content = str(message.get("content") or "").strip()
            if content:
                parts.append(f"{role}: {content}")

    limited_context = truncate_extracted_context(extracted_context)
    if limited_context:
        parts.append("Extracted file context:")
        parts.append(limited_context)

    parts.append("Current user message:")
    parts.append(current_message or "")
    return "\n\n".join(parts)


def truncate_extracted_context(value: str) -> str:
    return (value or "")[:get_context_max_chars()]


def guard_chat_response(response: str, tool_used: bool = False) -> str:
    text = response or ""
    if tool_used or not _claims_online_lookup(text):
        return text

    if ONLINE_CLAIM_GUARD_MESSAGE.strip() in text:
        return text

    return text.rstrip() + ONLINE_CLAIM_GUARD_MESSAGE


def _answer_with_deterministic_tool(
    task_type: ChatTaskType,
    message: str,
) -> dict[str, Any] | None:
    if task_type == ChatTaskType.DATE_TIME:
        result = answer_datetime_question(message)
        if result and result.confidence >= 0.9:
            return {
                "answer": result.answer,
                "tool_name": result.tool_name,
            }

    if task_type == ChatTaskType.MATH_CALCULATION:
        result = answer_calculation_question(message)
        if result and result.confidence >= 0.9:
            return {
                "answer": result.answer,
                "tool_name": result.tool_name,
            }

    return None


def _claims_online_lookup(text: str) -> bool:
    lowered = (text or "").lower()
    claim_patterns = (
        "i searched online",
        "i looked online",
        "i browsed",
        "i checked the web",
        "according to online sources",
        "from the search results",
        "i found online",
        "live sources",
        "current online",
    )
    return any(pattern in lowered for pattern in claim_patterns)


def _touch_session(session_id: str) -> None:
    session_file = _session_dir(session_id) / "session.json"
    if not session_file.exists():
        return
    session = _read_json(session_file)
    session["updated_at"] = _now()
    _write_json(session_file, session)


def _update_session_title_and_mode(session_id: str, message: str, ai_mode: str) -> None:
    session_file = _session_dir(session_id) / "session.json"
    session = _read_json(session_file)
    if session.get("title") == "New Chat" and message:
        session["title"] = message[:60]
    session["ai_mode"] = ai_mode
    session["updated_at"] = _now()
    _write_json(session_file, session)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    ).hex()


def _hash_unlock_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_unlock_tokens(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    return data if isinstance(data, list) else []


def _parse_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed
