import os
import time

from dotenv import load_dotenv

from langchain_deepseek import ChatDeepSeek

from app.services.local_llm import LocalLLM
from app.utils.ai_usage_logger import log_ai_usage


load_dotenv()


class LoggedLLM:

    def __init__(
        self,
        llm,
        provider: str,
        model: str
    ):
        self.llm = llm
        self.provider = provider
        self.model = model

    def invoke(
        self,
        prompt: str,
        ticket_id: str = "",
        node_name: str = ""
    ):
        start_time = time.time()

        response = self.llm.invoke(prompt)

        duration = time.time() - start_time

        content = response.content

        usage_metadata = (
            getattr(response, "usage_metadata", None)
            or {}
        )

        response_metadata = (
            getattr(response, "response_metadata", None)
            or {}
        )

        token_usage = response_metadata.get(
            "token_usage",
            {}
        )

        input_tokens = (
            usage_metadata.get("input_tokens")
            or token_usage.get("prompt_tokens")
        )

        output_tokens = (
            usage_metadata.get("output_tokens")
            or token_usage.get("completion_tokens")
        )

        log_ai_usage(
            ticket_id=ticket_id,
            node_name=node_name,
            model=(
                response_metadata.get("model_name")
                or self.model
            ),
            provider=(
                response_metadata.get("model_provider")
                or self.provider
            ),
            prompt=prompt,
            response=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_seconds=duration
        )

        return response


def get_llm():

    provider = os.getenv(
        "LLM_PROVIDER",
        "DEEPSEEK"
    ).upper()

    if provider == "LOCAL":

        model = os.getenv("LOCAL_LLM_MODEL")

        return LocalLLM(
            endpoint=os.getenv("LOCAL_LLM_URL"),
            model=model
        )

    if provider == "DEEPSEEK":

        model = os.getenv("DEEPSEEK_MODEL")

        deepseek_llm = ChatDeepSeek(
            model=model,
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            temperature=0
        )

        return LoggedLLM(
            llm=deepseek_llm,
            provider="DEEPSEEK",
            model=model
        )

    raise ValueError(
        f"Unsupported provider: {provider}"
    )