"""LLM provider abstraction supporting Anthropic and OpenAI-compatible APIs.

Set LLM_PROVIDER in your .env to switch between providers:
  LLM_PROVIDER=anthropic   (default) – uses Anthropic SDK directly
  LLM_PROVIDER=openai      – uses OpenAI-compatible SDK (OpenAI, Azure, DeepSeek,
                              Groq, OpenRouter, DashScope / Qwen API, etc.)
                              via LLM_BASE_URL
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared data models
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool / function call requested by the model."""
    name: str
    input: Dict[str, Any]


@dataclass
class LLMResponse:
    """Normalised response returned by every provider."""
    text: Optional[str]          # present for plain text responses
    tool_calls: List[ToolCall]   # present for tool-use responses
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    """Common interface for all LLM back-ends."""

    @abstractmethod
    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a normalised LLMResponse."""

# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

class AnthropicProvider(BaseLLMProvider):
    """Wraps the official Anthropic SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        resp = self._client.messages.create(**kwargs)
        text: Optional[str] = None
        tool_calls: List[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(name=block.name, input=block.input))
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAIProvider(BaseLLMProvider):
    """Wraps the OpenAI SDK for any OpenAI-compatible endpoint.

    Works with: OpenAI, Azure OpenAI, DeepSeek, Groq, OpenRouter,
    Ollama (with openai-compatible server), and any other provider
    that speaks the OpenAI chat-completions API.

    Tool-use is mapped to OpenAI function-calling format and the
    response is normalised back to LLMResponse so callers are
    provider-agnostic.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", "dummy"),
            base_url=base_url or os.environ.get("LLM_BASE_URL") or None,
        )

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            # Convert Anthropic-style tool schema to OpenAI function format
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema") or t.get("parameters", {}),
                    },
                }
                for t in tools
            ]
            if tool_choice:
                # Map Anthropic {"type": "any"} → OpenAI "required"
                _type = tool_choice.get("type", "auto")
                kwargs["tool_choice"] = "required" if _type == "any" else _type

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        text: Optional[str] = msg.content or None
        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, input=args))

        usage = resp.usage
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider(
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseLLMProvider:
    """Return the appropriate provider instance.

    Args:
        provider: ``"anthropic"`` or ``"openai"`` (default: env ``LLM_PROVIDER``,
                  fallback ``"anthropic"``)
        api_key:  Override for the provider's API key.
        base_url: Base URL for OpenAI-compatible endpoints (ignored for Anthropic).
    """
    name = (provider or os.environ.get("LLM_PROVIDER", "anthropic")).lower()
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key)
    if name in (
        "openai",
        "azure",
        "deepseek",
        "groq",
        "openrouter",
        "ollama",
        "dashscope",
        "qwenapi",
        "qwencloud",
    ):
        return OpenAIProvider(api_key=api_key, base_url=base_url)
    raise ValueError(
        f"Unknown LLM_PROVIDER '{name}'. "
        "Supported values: anthropic, openai, azure, deepseek, groq, openrouter, "
        "ollama, dashscope, qwenapi, qwencloud"
    )
