from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import LLMConfig


@dataclass(slots=True)
class LLMRequest:
    system: str
    prompt: str
    temperature: float = 0.2


class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> str: ...


class OllamaProvider:
    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, request: LLMRequest) -> str:
        response = httpx.post(
            f"{self.config.ollama_host.rstrip('/')}/api/chat",
            json={
                "model": self.config.model,
                "stream": False,
                "options": {"temperature": request.temperature},
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


class OpenRouterProvider:
    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, request: LLMRequest) -> str:
        if not self.config.openrouter_api_key or not self.config.openrouter_model:
            raise RuntimeError("OpenRouter requires an API key and model")
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.config.openrouter_api_key}"},
            json={
                "model": self.config.openrouter_model,
                "temperature": request.temperature,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def create_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "ollama":
        return OllamaProvider(config)
    if config.provider == "openrouter":
        return OpenRouterProvider(config)
    raise ValueError(f"Unsupported LLM provider: {config.provider}")
