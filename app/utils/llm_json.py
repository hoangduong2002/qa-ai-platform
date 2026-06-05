import json
import re


def parse_json(text: str):

    if not text:
        raise ValueError(
            "Empty response"
        )

    text = text.strip()

    fenced_match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    object_start = text.find("{")
    object_end = text.rfind("}")

    array_start = text.find("[")
    array_end = text.rfind("]")

    if (
        array_start != -1
        and array_end != -1
        and array_start < object_start
    ):
        candidate = text[
            array_start:array_end + 1
        ]

        return json.loads(candidate)

    if (
        object_start != -1
        and object_end != -1
    ):
        candidate = text[
            object_start:object_end + 1
        ]

        return json.loads(candidate)

    raise ValueError(
        "No JSON found"
    )