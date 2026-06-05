from app.services.llm_service import get_llm
from app.utils.llm_json import parse_json

llm = get_llm()

response = llm.invoke(
    """
Return ONLY JSON.

{
  "name": "test"
}
"""
)

print("RAW:")
print(response.content)

parsed = parse_json(response.content)

print("PARSED:")
print(parsed)
print(parsed["name"])