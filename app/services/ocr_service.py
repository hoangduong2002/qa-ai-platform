import os
from pathlib import Path

import cv2
import pytesseract

from app.config.env_loader import load_project_env


load_project_env()

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng+fra")

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def crop_main_modal(image):
    height, width = image.shape[:2]

    # Crop vùng giữa màn hình, bỏ header và nền xám
    x1 = int(width * 0.18)
    x2 = int(width * 0.82)
    y1 = int(height * 0.05)
    y2 = int(height * 0.92)

    return image[y1:y2, x1:x2]


def preprocess_image(image_path: Path):
    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")

    image = crop_main_modal(image)

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=4,
        fy=4,
        interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.GaussianBlur(
        gray,
        (3, 3),
        0
    )

    _, processed = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    return processed


def extract_text_from_image(image_path: Path) -> str:
    processed = preprocess_image(image_path)

    debug_path = image_path.parent / f"{image_path.stem}_processed.png"
    cv2.imwrite(str(debug_path), processed)

    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 11",
        "--oem 3 --psm 12"
    ]

    results = []

    for config in configs:
        text = pytesseract.image_to_string(
            processed,
            lang=OCR_LANGUAGE,
            config=config
        ).strip()

        if text:
            results.append(text)

    if not results:
        return ""

    return max(
        results,
        key=len
    )
