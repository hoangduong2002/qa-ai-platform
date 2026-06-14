from app.services.ai_mode_context_service import get_non_portal_ai_mode
from app.services.llm_router_service import TASK_REQUIREMENT_ANALYSIS, call_text_llm

response = call_text_llm(
    task_type=TASK_REQUIREMENT_ANALYSIS,
    prompt="say hello",
    ai_mode=get_non_portal_ai_mode(),
    source_channel="smoke_test",
)

print(response)
