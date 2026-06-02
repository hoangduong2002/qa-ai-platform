from app.services.llm_service import get_llm
from app.utils.prompt_loader import load_prompt


def normalize_ocr_requirement(
    ocr_text: str
) -> str:

    if not ocr_text.strip():
        return ""

    llm = get_llm()

    prompt = load_prompt(
        "prompts/normalize_ocr_requirement.md"
    )

    final_prompt = prompt.replace(
        "{ocr_text}",
        ocr_text
    )

    response = llm.invoke(
        final_prompt
    )

    return response.content.strip()