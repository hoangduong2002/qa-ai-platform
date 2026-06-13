import os
import time
import logging

from langchain_deepseek import ChatDeepSeek

from app.config.env_loader import load_project_env
from app.services.local_llm import LocalLLM
from app.services.local_ai_config_service import (
    get_LOCAL_base_url,
    get_LOCAL_text_model,
)
from app.services.portal_ai_mode_service import assert_deepseek_allowed
from app.services.portal_job_service import get_current_job_id, limit_llm_call
from app.utils.ai_usage_logger import log_ai_usage


load_project_env()
logger = logging.getLogger(__name__)


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

        with limit_llm_call(self.provider):
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

        logger.info(
            "LLM service call job_id=%s ticket_id=%s node_name=%s provider=%s model=%s duration_seconds=%.2f",
            get_current_job_id(),
            ticket_id,
            node_name,
            self.provider,
            self.model,
            duration,
        )

        return response


def get_llm():

    provider = os.getenv(
        "LLM_PROVIDER",
        "DEEPSEEK"
    ).upper()

    if provider == "LOCAL":

        model = get_LOCAL_text_model()

        return LocalLLM(
            base_url=get_LOCAL_base_url(),
            model=model
        )

    if provider == "DEEPSEEK":
        assert_deepseek_allowed()

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
