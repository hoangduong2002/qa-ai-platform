import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "UTC"


@dataclass
class DateTimeToolResult:
    answer: str
    confidence: float
    tool_name: str = "datetime_tool"


def answer_datetime_question(message: str) -> DateTimeToolResult | None:
    text = (message or "").strip().lower()
    if not _is_datetime_question(text):
        return None

    now = datetime.now(_get_timezone())
    target = now

    if "tomorrow" in text or "ngày mai" in text:
        target = now + timedelta(days=1)
    elif "yesterday" in text or "hôm qua" in text:
        target = now - timedelta(days=1)

    include_time = any(
        marker in text
        for marker in ["time", "mấy giờ", "giờ hiện tại", "what's the time", "what is the time"]
    )
    include_weekday = any(
        marker in text
        for marker in ["weekday", "day of week", "what day", "thứ mấy"]
    )

    date_text = target.strftime("%Y-%m-%d")
    weekday_text = target.strftime("%A")
    timezone_name = str(now.tzinfo)

    if include_time:
        answer = (
            f"The current time is {now.strftime('%H:%M:%S')} on {now.strftime('%Y-%m-%d')} "
            f"({timezone_name})."
        )
    elif include_weekday:
        answer = f"{date_text} is {weekday_text} ({timezone_name})."
    else:
        answer = f"Today is {now.strftime('%Y-%m-%d')} ({weekday_text}, {timezone_name})."

    return DateTimeToolResult(answer=answer, confidence=1.0)


def _get_timezone() -> ZoneInfo:
    timezone_name = os.getenv("APP_TIMEZONE") or os.getenv("TZ") or DEFAULT_TIMEZONE
    if timezone_name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _is_datetime_question(text: str) -> bool:
    patterns = (
        r"\b(today|tomorrow|yesterday|date|time|weekday|day of week)\b",
        r"\bwhat day is it\b",
        r"\bngày\s+(hôm nay|mai|hôm qua)\b",
        r"\bhôm nay\b",
        r"\bngày mai\b",
        r"\bhôm qua\b",
        r"\bthứ mấy\b",
        r"\bmấy giờ\b",
        r"\bgiờ hiện tại\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
