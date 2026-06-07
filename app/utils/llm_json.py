import json
import re
from dataclasses import dataclass


@dataclass
class JSONParseDebugInfo:
    message: str
    line: int | None = None
    column: int | None = None
    position: int | None = None
    context: str = ""


class LLMJsonParseError(ValueError):
    def __init__(self, debug_info: JSONParseDebugInfo):
        self.debug_info = debug_info

        detail = debug_info.message

        if debug_info.line is not None and debug_info.column is not None:
            detail += f" at line {debug_info.line}, column {debug_info.column}"

        if debug_info.position is not None:
            detail += f" char {debug_info.position}"

        if debug_info.context:
            detail += f"\n\nContext around error:\n{debug_info.context}"

        super().__init__(detail)


def _strip_code_fence(text: str) -> str:
    text = text.strip()

    fenced_match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if fenced_match:
        return fenced_match.group(1).strip()

    return text


def _extract_json_candidate(text: str) -> str:
    text = text.strip()

    array_start = text.find("[")
    array_end = text.rfind("]")

    object_start = text.find("{")
    object_end = text.rfind("}")

    candidates = []

    if array_start != -1 and array_end != -1 and array_end > array_start:
        candidates.append(
            (
                array_start,
                text[array_start:array_end + 1],
            )
        )

    if object_start != -1 and object_end != -1 and object_end > object_start:
        candidates.append(
            (
                object_start,
                text[object_start:object_end + 1],
            )
        )

    if not candidates:
        raise LLMJsonParseError(
            JSONParseDebugInfo(
                message="No JSON array or object found in LLM response.",
                context=text[:1000],
            )
        )

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1].strip()


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _build_error_context(text: str, position: int | None, radius: int = 500) -> str:
    if position is None:
        return text[:1000]

    start = max(position - radius, 0)
    end = min(position + radius, len(text))

    return text[start:end]


def _json_loads_with_debug(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMJsonParseError(
            JSONParseDebugInfo(
                message=error.msg,
                line=error.lineno,
                column=error.colno,
                position=error.pos,
                context=_build_error_context(text, error.pos),
            )
        ) from error


def parse_json(text: str):
    """
    Parse JSON returned by LLM.

    Supports:
    - raw JSON array/object
    - fenced ```json block
    - response with extra text before/after JSON
    - simple trailing comma cleanup

    Does not silently swallow invalid JSON.
    If parsing fails, raises LLMJsonParseError with useful context.
    """

    if not text:
        raise LLMJsonParseError(
            JSONParseDebugInfo(
                message="Empty LLM response.",
            )
        )

    stripped_text = _strip_code_fence(text)

    attempts = []

    attempts.append(stripped_text)

    try:
        candidate = _extract_json_candidate(stripped_text)
        attempts.append(candidate)
    except LLMJsonParseError:
        candidate = stripped_text

    attempts.append(_remove_trailing_commas(candidate))

    last_error = None

    for candidate_text in attempts:
        try:
            return json.loads(candidate_text)
        except json.JSONDecodeError as error:
            last_error = error

    if last_error:
        raise LLMJsonParseError(
            JSONParseDebugInfo(
                message=last_error.msg,
                line=last_error.lineno,
                column=last_error.colno,
                position=last_error.pos,
                context=_build_error_context(
                    attempts[-1],
                    last_error.pos,
                ),
            )
        ) from last_error

    raise LLMJsonParseError(
        JSONParseDebugInfo(
            message="Unknown JSON parsing error.",
            context=stripped_text[:1000],
        )
    )