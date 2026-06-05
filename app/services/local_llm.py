import time
import requests

from app.utils.ai_usage_logger import log_ai_usage


class LLMResponse:

    def __init__(self, content: str):
        self.content = content


class LocalLLM:

    def __init__(
        self,
        endpoint: str,
        model: str
    ):
        self.endpoint = endpoint
        self.model = model
        self.provider = "LOCAL"

    def invoke(
        self,
        prompt: str,
        ticket_id: str = "",
        node_name: str = ""
    ):
        start_time = time.time()

        response = requests.post(
            self.endpoint,
            headers={
                "Content-Type": "application/json"
            },
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "model": self.model
            },
            timeout=300
        )

        duration = time.time() - start_time

        response.raise_for_status()

        data = response.json()

        content = (
            data["choices"][0]
            ["message"]
            ["content"]
        )

        usage = data.get("usage", {})

        log_ai_usage(
            ticket_id=ticket_id,
            node_name=node_name,
            model=self.model,
            provider=self.provider,
            prompt=prompt,
            response=content,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            duration_seconds=duration
        )

        return LLMResponse(
            content=content
        )