"""Provider adapters for OpenAI and Gemini with streaming support."""

from __future__ import annotations

import os
from typing import Dict, Generator, List

import google.genai as genai
from openai import OpenAI


class ProviderError(RuntimeError):
    pass


class BaseProvider:
    def stream_chat(self, messages: List[Dict[str, str]], model: str) -> Generator[str, None, None]:
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is required for provider 'openai'")
        self.client = OpenAI(api_key=api_key)

    def stream_chat(self, messages: List[Dict[str, str]], model: str) -> Generator[str, None, None]:
        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is required for provider 'gemini'")
        self.client = genai.Client(api_key=api_key)

    def stream_chat(self, messages: List[Dict[str, str]], model: str) -> Generator[str, None, None]:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        response = self.client.models.generate_content(
            model=f"models/{model}" if not model.startswith("models/") else model,
            contents=prompt,
            stream=True,
        )
        
        for chunk in response:
            if hasattr(chunk, "text") and chunk.text:
                yield chunk.text


def build_provider(name: str) -> BaseProvider:
    normalized = name.lower()
    if normalized == "openai":
        return OpenAIProvider(api_key=os.getenv("OPENAI_API_KEY", ""))
    if normalized == "gemini":
        return GeminiProvider(api_key=os.getenv("GEMINI_API_KEY", ""))
    raise ProviderError(f"Unknown provider: {name}")
