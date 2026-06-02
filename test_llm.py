from app.services.llm_service import llm

response = llm.invoke(
    "Generate 3 test scenarios for login functionality."
)

print(response.content)