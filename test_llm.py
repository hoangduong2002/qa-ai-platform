from app.services.llm_service import get_llm

llm = get_llm()

response = llm.invoke(
    "say hello"
)

print(response)

print("------")

print(response.response_metadata)

print("------")

print(response.usage_metadata)