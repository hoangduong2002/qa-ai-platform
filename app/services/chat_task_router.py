import re
from enum import StrEnum


class ChatTaskType(StrEnum):
    GENERAL_CHAT = "GENERAL_CHAT"
    QA_ANALYSIS = "QA_ANALYSIS"
    FILE_SUMMARY = "FILE_SUMMARY"
    DATE_TIME = "DATE_TIME"
    MATH_CALCULATION = "MATH_CALCULATION"
    CODE_HELP = "CODE_HELP"
    CURRENT_INFO = "CURRENT_INFO"
    UNKNOWN = "UNKNOWN"


DATE_TIME_PATTERNS = (
    r"\b(today|tomorrow|yesterday|date|time|weekday|day of week|current day)\b",
    r"\bwhat day is it\b",
    r"\bwhat('s| is) the time\b",
    r"\bngày\s+(hôm nay|mai|hôm qua)\b",
    r"\bhôm nay\b",
    r"\bngày mai\b",
    r"\bhôm qua\b",
    r"\bthứ mấy\b",
    r"\bmấy giờ\b",
    r"\bgiờ hiện tại\b",
)
MATH_PATTERN = re.compile(r"^[\s\d().,+\-*/%^=xX]+$")
MATH_WORD_PATTERN = re.compile(
    r"\b(calculate|compute|solve|sum|plus|minus|multiply|divide|"
    r"tính|bằng bao nhiêu|cộng|trừ|nhân|chia)\b",
    re.IGNORECASE,
)
QA_PATTERNS = (
    r"\btest case\b",
    r"\bqa\b",
    r"\brequirement\b",
    r"\bbug\b",
    r"\bautomation\b",
    r"\bsecurity test\b",
    r"\bperformance test\b",
)
FILE_SUMMARY_PATTERNS = (
    r"\bsummarize\b.*\b(file|document|attachment)\b",
    r"\bsummary\b.*\b(file|document|attachment)\b",
    r"\btóm tắt\b",
)
CODE_PATTERNS = (
    r"\bcode\b",
    r"\bpython\b",
    r"\bjavascript\b",
    r"\btypescript\b",
    r"\bfunction\b",
    r"\berror\b",
    r"\bdebug\b",
)
CURRENT_INFO_PATTERNS = (
    r"\blatest\b",
    r"\bcurrent news\b",
    r"\btoday's news\b",
    r"\bstock price\b",
    r"\bexchange rate\b",
    r"\bweather\b",
    r"\bnow online\b",
    r"\bmới nhất\b",
    r"\btin tức\b",
)


def classify_chat_task(message: str, has_file_context: bool = False) -> ChatTaskType:
    text = (message or "").strip().lower()

    if not text and has_file_context:
        return ChatTaskType.FILE_SUMMARY

    if not text:
        return ChatTaskType.UNKNOWN

    if _matches_any(text, DATE_TIME_PATTERNS):
        return ChatTaskType.DATE_TIME

    if _looks_like_math(text):
        return ChatTaskType.MATH_CALCULATION

    if has_file_context and _matches_any(text, FILE_SUMMARY_PATTERNS):
        return ChatTaskType.FILE_SUMMARY

    if _matches_any(text, CURRENT_INFO_PATTERNS):
        return ChatTaskType.CURRENT_INFO

    if _matches_any(text, QA_PATTERNS):
        return ChatTaskType.QA_ANALYSIS

    if _matches_any(text, CODE_PATTERNS):
        return ChatTaskType.CODE_HELP

    return ChatTaskType.GENERAL_CHAT


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _looks_like_math(text: str) -> bool:
    normalized = text.replace("=", "").strip()
    if not normalized:
        return False

    has_operator = any(operator in normalized for operator in ["+", "-", "*", "/", "%", "^", "x"])
    has_digit = any(character.isdigit() for character in normalized)
    if has_operator and has_digit and MATH_PATTERN.fullmatch(normalized):
        return True

    return bool(has_digit and MATH_WORD_PATTERN.search(text))
