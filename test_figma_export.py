import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.services.figma_requirement_service import (
    FigmaFileReference,
    FigmaPageScope,
    _dedupe_page_scopes,
    extract_figma_context_from_jira_texts,
    extract_figma_references_from_texts,
)
from app.services.local_ai_config_service import (
    get_local_ai_provider,
    get_LOCAL_base_url,
    get_LOCAL_vision_model,
    is_figma_local_vision_enabled,
    is_local_ai_enabled,
    is_local_vision_enabled,
)


load_dotenv()

os.environ["FIGMA_IMAGE_EXPORT_BATCH_SIZE"] = os.getenv(
    "FIGMA_TEST_IMAGE_EXPORT_BATCH_SIZE",
    "10",
)

print("Local AI config:")
print("LOCAL_AI_ENABLED:", is_local_ai_enabled())
print("LOCAL_AI_PROVIDER:", get_local_ai_provider())
print("LOCAL_VISION_ENABLED:", is_local_vision_enabled())
print("FIGMA_LOCAL_VISION_ENABLED:", os.getenv("FIGMA_LOCAL_VISION_ENABLED", ""))
print("figma local vision enabled:", is_figma_local_vision_enabled())
print("LOCAL_BASE_URL:", get_LOCAL_base_url())
print("LOCAL_VISION_MODEL:", get_LOCAL_vision_model())
print()


def run_offline_dedupe_smoke_test() -> None:
    reference = FigmaFileReference(
        file_key="aUOiDYLjnOCn2j3xR6qwwV",
        source_urls=[
            "https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=7-95540&m=dev",
            "https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=3-17634&m=dev",
            "https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=802-16701&m=dev",
        ],
        entry_node_ids=["7:95540", "3:17634", "802:16701"],
    )
    page_scopes = [
        FigmaPageScope(
            file_key=reference.file_key,
            page_id="2:21896",
            page_name="INSi",
            entry_node_ids=["7:95540", "3:17634", "802:16701"],
        ),
        FigmaPageScope(
            file_key=reference.file_key,
            page_id="2:21896",
            page_name="INSi",
            entry_node_ids=["7:95540"],
        ),
    ]

    deduped = _dedupe_page_scopes(reference, page_scopes)
    first = deduped[0]

    print("Offline dedupe smoke test:")
    print("Deduped page scopes:", len(deduped))
    print("Merged source links:", len(first.source_links))
    print("Merged entry node ids:", len(first.entry_node_ids))
    print("Duplicate link count:", first.duplicate_link_count)
    print("Skipped duplicate pages:", len(first.skipped_duplicate_pages))
    print()


run_offline_dedupe_smoke_test()


ticket_id = "TEST-FIGMA"

texts = [
    # Multiple Jira fields can contain links with different node IDs on the same page.
    "Description link: https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=7-95540&m=dev",
    "Comment link same page: https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=3-17634&m=dev",
    "Subtask link same page: https://www.figma.com/design/aUOiDYLjnOCn2j3xR6qwwV/Fiche-patient?node-id=802-16701&m=dev",
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

for reference in references:
    file_root = output_root / reference.file_key

    for page_dir in file_root.iterdir():
        if not page_dir.is_dir():
            continue

        layers_file = page_dir / "extracted_layers.json"
        screens_file = page_dir / "extracted_screens.json"

        if not layers_file.exists() or not screens_file.exists():
            continue

        layers = json.loads(layers_file.read_text(encoding="utf-8"))
        screens = json.loads(screens_file.read_text(encoding="utf-8"))
        non_section_layers = [
            layer for layer in layers
            if layer.get("type") != "SECTION"
        ]
        non_frame_screens = [
            screen for screen in screens
            if screen.get("type") != "FRAME"
        ]

        print()
        print("Page output:", page_dir)
        print("SECTION layers:", len(layers))
        print("FRAME screens:", len(screens))
        print("Non-SECTION layers:", len(non_section_layers))
        print("Non-FRAME screens:", len(non_frame_screens))
        print("Flow debug:", page_dir / "flow_connectors_debug.json")

        metadata_file = page_dir / "page_metadata.json"

        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            print("Merged source links:", len(metadata.get("source_links", [])))
            print("Entry node ids:", len(metadata.get("entry_node_ids", [])))
            print("Duplicate link count:", metadata.get("duplicate_link_count", 0))
            print(
                "Skipped duplicate pages:",
                len(metadata.get("skipped_duplicate_pages", [])),
            )
