from app.services.ai_mode_context_service import get_non_portal_ai_mode
from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm
from app.utils.llm_json import parse_json

response = call_text_llm(
    task_type=TASK_REQUIREMENT_ANALYSIS,
    prompt="""
Return ONLY JSON.

{
  "name": "test"
}
""",
    ai_mode=get_non_portal_ai_mode(),
    source_channel="smoke_test",
)

print("RAW:")
print(response)

parsed = parse_json(response)

print("PARSED:")
print(parsed)
print(parsed["name"])
