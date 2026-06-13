import time
import requests

from app.services.portal_ai_mode_service import assert_local_ai_allowed
from app.services.portal_job_service import (
    limit_llm_call,
    limit_LOCAL_call,
)
from app.utils.ai_usage_logger import log_ai_usage


class LLMResponse:

    def __init__(self, content: str):
        self.content = content


class LocalLLM:

    def __init__(
        self,
        base_url: str,
        model: str
    ):
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self.model = model
        self.provider = "LOCAL"

    def invoke(
        self,
        prompt: str,
        ticket_id: str = "",
        node_name: str = ""
    ):
        start_time = time.time()

        assert_local_ai_allowed()

        with limit_llm_call(self.provider), limit_LOCAL_call(self.provider):
            response = requests.post(
                f"{self.base_url}/api/chat",
                headers={
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0
                    }
                },
                timeout=300
            )

        duration = time.time() - start_time

        response.raise_for_status()

        data = response.json()

        content = (
            data.get("message", {}).get("content")
            or data.get("response")
            or ""
        )

        if not content.strip():
            raise RuntimeError(
                "LOCAL LLM returned empty response. "
                f"model={self.model}, base_url={self.base_url}"
            )

        input_tokens = (
            data.get("prompt_eval_count")
            or data.get("usage", {}).get("prompt_tokens")
        )
        output_tokens = (
            data.get("eval_count")
            or data.get("usage", {}).get("completion_tokens")
        )

        log_ai_usage(
            ticket_id=ticket_id,
            node_name=node_name,
            model=self.model,
            provider=self.provider,
            prompt=prompt,
            response=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_seconds=duration
        )

        return LLMResponse(
            content=content
        )
