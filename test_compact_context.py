import sys

from dotenv import load_dotenv

from app.services.requirement_compact_context_service import (
    build_compact_requirement_context,
)


load_dotenv()


ticket_id = sys.argv[1] if len(sys.argv) > 1 else "TEST-FIGMA"

result = build_compact_requirement_context(ticket_id)

print("Output path:", result["analysis_root"])
print("Detected mode:", result["detected_mode"])
print("Source files:", result["source_files_count"])
print("Screens:", result["screen_count"])
print(
    "Screens with vision analysis:",
    result["screens_with_vision_analysis_count"],
)
print("Attachments:", result["attachment_count"])
print(
    "Attachments with vision analysis:",
    result["attachments_with_vision_analysis_count"],
)
print("Sections:", result["section_count"])
print("Section summaries:", result.get("section_summary_count", 0))
print("Chunks:", result["chunk_count"])
print("Partial summaries:", result["partial_summary_count"])
print("Compact context length:", result["compact_context_length"])
print("Truncated:", result["truncated"])

warnings = result.get("warnings") or []

if warnings:
    print()
    print("Warnings:")
    for warning in warnings:
        print(f"- {warning}")
else:
    print("Warnings: none")
