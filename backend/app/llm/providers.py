from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx


class LlmProvider(ABC):
    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class MockProvider(LlmProvider):
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return (
            "Nao ha LLM configurado. A resposta abaixo foi montada por recuperacao de evidencias locais.\n\n"
            + user_prompt[:2500]
        )


class OpenAiProvider(LlmProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]


class OllamaProvider(LlmProvider):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]


def build_provider(settings) -> LlmProvider:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAiProvider(settings.openai_api_key, settings.openai_model)
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    return MockProvider()

