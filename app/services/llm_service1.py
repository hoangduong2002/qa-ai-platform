from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
import os

#load_dotenv()

#llm = ChatDeepSeek(
#    model="deepseek-v4-flash",
#    api_key=os.getenv("DEEPSEEK_API_KEY"),
#    temperature=0
#)


def _deepseek_model() -> str:
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if "v4-pro" in model.strip().lower() and os.getenv(
        "ALLOW_DEEPSEEK_PRO",
        "",
    ).strip().lower() not in {"1", "true", "yes", "y", "on"}:
        raise RuntimeError(
            "deepseek-v4-pro is disabled by cost guard. "
            "Set ALLOW_DEEPSEEK_PRO=true only if you intentionally want to use Pro."
        )

    return model


def get_llm():

    return ChatDeepSeek(
        model=_deepseek_model(),
        temperature=0
    )
