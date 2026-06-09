from dotenv import load_dotenv
from pathlib import Path

from app.services.requirement_sanitization_service import (
    sanitize_requirement_for_analysis,
)

load_dotenv()

ticket_id = "TEST-SANITIZE"

raw = Path("requirements/EVNWCL-5221/source/jira/EVNWCL-5221.md").read_text(
    encoding="utf-8",
)

sanitized = sanitize_requirement_for_analysis(
    ticket_id=ticket_id,
    raw_requirement=raw,
)

print(sanitized[:3000])