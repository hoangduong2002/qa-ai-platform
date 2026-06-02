from pathlib import Path

from app.services.ocr_service import (
    extract_text_from_image
)


image_path = Path(
    "sample_requirement.png"
)

text = extract_text_from_image(
    image_path
)

print(text)