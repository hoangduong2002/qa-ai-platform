from pathlib import Path

from docx import Document
from pptx import Presentation

from app.services.ocr_service import (
    extract_text_from_image
)
from app.utils.ocr_normalizer import normalize_ocr_requirement

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp"
}


def extract_txt_text(
    file_path: Path
) -> str:

    return file_path.read_text(
        encoding="utf-8"
    )


def extract_docx_text(
    file_path: Path
) -> str:

    doc = Document(file_path)

    return "\n".join(
        paragraph.text
        for paragraph in doc.paragraphs
        if paragraph.text.strip()
    )


def extract_image_text(
    file_path: Path
) -> str:

    raw_text = extract_text_from_image(
        file_path
    )

    normalized_text = normalize_ocr_requirement(
        raw_text
    )

    return normalized_text


def extract_pptx_text(
    file_path: Path
) -> str:

    prs = Presentation(
        file_path
    )

    output = []

    image_index = 1

    image_output_dir = (
        file_path.parent
        / "extracted_images"
    )

    image_output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    for slide_index, slide in enumerate(
        prs.slides,
        start=1
    ):

        slide_parts = []

        for shape in slide.shapes:

            if hasattr(shape, "text"):
                text = shape.text.strip()

                if text:
                    slide_parts.append(
                        text
                    )

            if hasattr(shape, "image"):

                image = shape.image

                image_path = (
                    image_output_dir
                    / f"slide_{slide_index}_image_{image_index}.{image.ext}"
                )

                image_path.write_bytes(
                    image.blob
                )

                image_text = extract_image_text(
                    image_path
                )

                if image_text:
                    slide_parts.append(
                        "# Extracted Image Text\n"
                        + image_text
                    )

                image_index += 1

        if slide_parts:
            output.append(
                f"# Slide {slide_index}\n"
                + "\n\n".join(slide_parts)
            )

    return "\n\n".join(output)


def extract_file_text(
    file_path: Path
) -> str:

    suffix = file_path.suffix.lower()

    if suffix in [".txt", ".md"]:
        return extract_txt_text(
            file_path
        )

    if suffix == ".docx":
        return extract_docx_text(
            file_path
        )

    if suffix == ".pptx":
        return extract_pptx_text(
            file_path
        )

    if suffix in IMAGE_EXTENSIONS:
        return extract_image_text(
            file_path
        )

    raise ValueError(
        f"Unsupported file type: {suffix}"
    )