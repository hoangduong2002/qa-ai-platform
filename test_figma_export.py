from pathlib import Path

from dotenv import load_dotenv

from app.services.figma_requirement_service import (
    extract_figma_context_from_jira_texts,
    extract_figma_references_from_texts,
)

load_dotenv()


ticket_id = "TEST-FIGMA"

texts = [
    # Thay bằng Figma link thật lấy từ Jira.
    # Link cần có node-id để service resolve đúng target page.
    "https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=7-95540&m=dev"
]

references = extract_figma_references_from_texts(texts)

print("Detected Figma references:")
for reference in references:
    print(reference)

context = extract_figma_context_from_jira_texts(
    ticket_id=ticket_id,
    texts=texts,
)

print()
print(context[:5000])

output_root = Path("requirements") / ticket_id / "source" / "figma"

print()
print("Output exists:", output_root.exists())
print("Output path:", output_root.resolve())