from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import LLMConfig


@dataclass(slots=True)
class LLMRequest:
    system: str
    prompt: str
    temperature: float = 0.2
    json_mode: bool = False
    web_search: bool = False


class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> str: ...


class OllamaProvider:
    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, request: LLMRequest) -> str:
        payload = {
            "model": self.config.model,
            "stream": False,
            "options": {"temperature": request.temperature},
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
        }
        if request.json_mode:
            payload["format"] = "json"
        response = httpx.post(f"{self.config.ollama_host.rstrip('/')}/api/chat", json=payload, timeout=180)
        response.raise_for_status()
        return response.json()["message"]["content"]


class OpenRouterProvider:
    def __init__(self, config: LLMConfig):
        self.config = config

    @staticmethod
    def _error(response: httpx.Response) -> RuntimeError:
        try:
            data = response.json()
            message = data.get("error", {}).get("message") or data.get("message")
        except (ValueError, TypeError):
            message = None
        if response.status_code == 401:
            return RuntimeError(
                "OpenRouter authentication failed (401). Check that the API key is valid, active, "
                "and starts with 'sk-or-'." + (f" OpenRouter says: {message}" if message else "")
            )
        return RuntimeError(
            f"OpenRouter request failed ({response.status_code})." + (f" OpenRouter says: {message}" if message else "")
        )

    def generate(self, request: LLMRequest) -> str:
        if not self.config.openrouter_api_key or not self.config.openrouter_model:
            raise RuntimeError("OpenRouter requires an API key and model")
        payload = {
            "model": self.config.openrouter_model,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.web_search:
            payload["plugins"] = [{"id": "web", "max_results": 5}]
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.openrouter_api_key.strip()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
        if not response.is_success:
            raise self._error(response)
        return response.json()["choices"][0]["message"]["content"]


def create_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "ollama":
        return OllamaProvider(config)
    if config.provider == "openrouter":
        return OpenRouterProvider(config)
    raise ValueError(f"Unsupported LLM provider: {config.provider}")
