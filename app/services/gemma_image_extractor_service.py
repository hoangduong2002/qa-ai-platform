import base64
import json
import os
import io
import urllib.error
import urllib.request
from pathlib import Path
from PIL import Image

from app.services.local_ai_config_service import (
    get_ollama_base_url,
    get_ollama_vision_model,
)


DEFAULT_IMAGE_EXTRACTION_PROMPT = """
You are a QA requirement extraction assistant.

Analyze the provided image and extract useful requirement information for software testing.

Return Markdown with these sections only:

# Screen Summary
Briefly describe only what is clearly visible. Maximum 3 sentences.

# Visible Text
Extract clearly readable text only.
Do not repeat the same text.
If text is unclear, write "[UNREADABLE]".

# UI Elements
List visible UI elements such as buttons, fields, labels, tables, menus, error messages, icons, checkboxes, and dialogs.
Do not invent UI elements.

# Possible User Actions
List actions directly supported by visible UI elements only.
Do not assume missing steps.

# Potential Validation Rules
List validation rules only if they are explicitly visible in the image.
If no validation message, required marker, format hint, or constraint is visible, write "None visible".
Do not infer generic validation rules.

# QA Test Notes
List only direct test notes based on visible UI elements and readable text.
Do not create test cases for inferred business flow.
If there is not enough visible information, write "Not enough visible information".

Rules:
- Do not hallucinate.
- Do not invent hidden requirements.
- Do not invent navigation links, menus, buttons, fields, labels, names, or pages.
- Do not guess screen resolution, platform, device type, watermark, or business context unless clearly visible.
- Preserve original labels and visible text when possible.
- Do not repeat the same visible text more than once.
- If the image is unclear, say "[UNCLEAR]" instead of guessing.
- If text cannot be read, mark it as "[UNREADABLE]".
- Do not assume missing steps.
- Do not create business rules.
- Do not infer domain, business process, appointment type, medical/dental context, e-commerce context, or navigation menu unless the text is clearly visible.
- If less than 3 words are readable in an area, mark it as "[UNREADABLE]" instead of guessing.
- Do not create validation rules based only on common web form behavior.
- Do not explain what you would do if an image were provided.
- Maximum 10 bullet points per section.
- Keep the answer concise.
""".strip()


def _get_gemma_base_url() -> str:
    base_url = get_ollama_base_url()

    if not base_url:
        raise ValueError(
            "OLLAMA_BASE_URL is missing. "
            "Example: OLLAMA_BASE_URL=http://localhost:11434"
        )

    return base_url.rstrip("/")


def _get_gemma_model() -> str:
    model = get_ollama_vision_model()

    if not model:
        raise ValueError(
            "OLLAMA_VISION_MODEL is missing. "
            "Set it to the model name shown by `ollama list`."
        )

    return model


def _get_timeout() -> int:
    try:
        return int(os.getenv("GEMMA_VISION_TIMEOUT", "180"))
    except Exception:
        return 180
    
    
def _normalize_line_for_dedup(line: str) -> str:
    normalized = (line or "").strip().lower()

    prefixes = [
        "- ",
        "* ",
        "• ",
    ]

    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()

    normalized = " ".join(normalized.split())

    return normalized


def _deduplicate_markdown_lines(text: str) -> str:
    lines = (text or "").splitlines()

    seen = set()
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            cleaned_lines.append(line)
            continue

        if stripped.startswith("#"):
            cleaned_lines.append(line)
            continue

        key = _normalize_line_for_dedup(stripped)

        if key in seen:
            continue

        seen.add(key)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _looks_like_low_quality_vision_response(text: str) -> bool:
    normalized = (text or "").lower()

    generic_navigation_patterns = [
        "home, about us, contact us",
        "about us",
        "privacy policy",
        "terms of service",
        "login/logout",
        "shop",
        "cart",
        "profile",
        "logout",
    ]

    generic_domain_patterns = [
        "dental appointment",
        "appointment scheduler",
        "online dental",
        "e-commerce",
        "shopping cart",
    ]

    generic_hits = sum(
        1 for pattern in generic_navigation_patterns + generic_domain_patterns
        if pattern in normalized
    )

    if generic_hits >= 2:
        return True

    lines = [
        _normalize_line_for_dedup(line)
        for line in text.splitlines()
        if _normalize_line_for_dedup(line)
    ]

    if not lines:
        return True

    unique_lines = set(lines)
    duplicate_ratio = 1 - (len(unique_lines) / max(len(lines), 1))

    if len(lines) >= 20 and duplicate_ratio >= 0.45:
        return True

    return False
    
    
def _normalize_image_to_png_base64(image_path: Path) -> str:
    """
    Convert image to PNG RGB before sending to Ollama.

    This helps avoid errors when Jira pasted images are webp, palette PNG,
    CMYK JPG, transparent PNG, or other formats/modes that Ollama/LLaVA
    may not load correctly.
    """
    with Image.open(image_path) as image:
        image.load()

        if image.mode != "RGB":
            image = image.convert("RGB")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)

        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def extract_image_with_gemma(
    image_path: str | Path,
    prompt: str | None = None,
) -> str:
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if image_path.stat().st_size <= 0:
        raise ValueError(f"Image file is empty: {image_path}")

    base_url = _get_gemma_base_url()
    model = _get_gemma_model()
    timeout = _get_timeout()

    image_base64 = _normalize_image_to_png_base64(image_path)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt or DEFAULT_IMAGE_EXTRACTION_PROMPT,
                "images": [
                    image_base64
                ],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": 1000,
            "repeat_penalty": 1.25,
        },
    }

    request = urllib.request.Request(
        url=f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="ignore")

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            "Gemma image extraction failed with HTTP "
            f"{error.code}: {error_body}\n"
            f"Model: {model}\n"
            f"URL: {base_url}/api/chat\n"
            f"Image: {image_path}\n"
            f"Image size: {image_path.stat().st_size}\n"
            f"PNG base64 length: {len(image_base64)}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Cannot connect to Ollama vision server at {base_url}. "
            f"Please check LAN IP, firewall, OLLAMA_HOST, and port 11434. "
            f"Error: {error}"
        ) from error

    data = json.loads(raw_body)

    extracted_text = (
        data.get("message", {}).get("content")
        or data.get("response")
        or ""
    ).strip()

    if not extracted_text:
        raise RuntimeError(
            f"Ollama vision model returned empty response for image: {image_path}. "
            f"Raw response: {raw_body[:1000]}"
        )

    if _looks_like_no_image_response(extracted_text):
        raise RuntimeError(
            "Ollama vision model did not receive/read the image correctly. "
            f"Model: {model}. "
            f"Image: {image_path}. "
            f"Response: {extracted_text[:500]}"
        )

    extracted_text = _deduplicate_markdown_lines(extracted_text)

    if _looks_like_low_quality_vision_response(extracted_text):
        raise RuntimeError(
            "Ollama vision output looks low-quality or hallucinated. "
            "Extraction was rejected to avoid polluting requirement context. "
            f"Model: {model}. "
            f"Image: {image_path}. "
            f"Response preview: {extracted_text[:800]}"
        )

    return extracted_text


def _looks_like_no_image_response(text: str) -> bool:
    normalized = (text or "").lower()

    patterns = [
        "no image was provided",
        "no visual content was provided",
        "please provide the image",
        "please upload the image",
        "cannot analyze the image because no",
        "cannot describe the image or extract",
        "no image provided",
    ]

    return any(pattern in normalized for pattern in patterns)
