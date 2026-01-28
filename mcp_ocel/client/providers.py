"""Provider adapters for OpenAI and Gemini with streaming support."""

from __future__ import annotations

import os
import sys
from typing import Dict, Generator, List

# Add parent directory to path for importing from server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_ocel.server.typing_ocel import ChatMessageDict

import google.genai as genai
from openai import OpenAI


class ProviderError(RuntimeError):
    pass


class BaseProvider:
    """Base class for LLM providers."""
    
    def stream_chat(
        self, messages: List[ChatMessageDict], model: str
    ) -> Generator[str, None, None]:
        """Stream chat completions from the LLM.
        
        Args:
            messages: List of chat messages with role and content.
            model: Model name to use.
            
        Yields:
            Text chunks from the model response.
        """
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    """OpenAI API provider."""
    
    def __init__(self, api_key: str) -> None:
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key.
            
        Raises:
            ProviderError: If API key is missing.
        """
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is required for provider 'openai'")
        self.client = OpenAI(api_key=api_key)

    def stream_chat(
        self, messages: List[ChatMessageDict], model: str
    ) -> Generator[str, None, None]:
        """Stream chat completions from OpenAI.
        
        Args:
            messages: List of chat messages.
            model: OpenAI model name.
            
        Yields:
            Text chunks from OpenAI response.
        """
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
    """Google Gemini API provider."""
    
    def __init__(self, api_key: str) -> None:
        """Initialize Gemini provider.
        
        Args:
            api_key: Gemini API key.
            
        Raises:
            ProviderError: If API key is missing.
        """
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is required for provider 'gemini'")
        self.client = genai.Client(api_key=api_key)

    def stream_chat(
        self, messages: List[ChatMessageDict], model: str
    ) -> Generator[str, None, None]:
        """Stream chat completions from Gemini.
        
        Args:
            messages: List of chat messages.
            model: Gemini model name.
            
        Yields:
            Text chunks from Gemini response.
        """
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        response = self.client.models.generate_content_stream(
            model=f"models/{model}" if not model.startswith("models/") else model,
            contents=prompt
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
