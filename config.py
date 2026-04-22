import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


class LLMConfig(BaseModel):
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""


class Settings:
    def __init__(self) -> None:
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
        self.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-4-6")
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "")

        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

        self.STYLE_AGENT_LLM_PROVIDER = os.getenv("STYLE_AGENT_LLM_PROVIDER", "")
        self.STYLE_AGENT_LLM_MODEL = os.getenv("STYLE_AGENT_LLM_MODEL", "")
        self.STYLE_AGENT_LLM_BASE_URL = os.getenv("STYLE_AGENT_LLM_BASE_URL", "")
        self.STYLE_AGENT_LLM_API_KEY = os.getenv("STYLE_AGENT_LLM_API_KEY", "")

        self.SECURITY_AGENT_LLM_PROVIDER = os.getenv("SECURITY_AGENT_LLM_PROVIDER", "")
        self.SECURITY_AGENT_LLM_MODEL = os.getenv("SECURITY_AGENT_LLM_MODEL", "")
        self.SECURITY_AGENT_LLM_BASE_URL = os.getenv("SECURITY_AGENT_LLM_BASE_URL", "")
        self.SECURITY_AGENT_LLM_API_KEY = os.getenv("SECURITY_AGENT_LLM_API_KEY", "")

        self.LOGIC_AGENT_LLM_PROVIDER = os.getenv("LOGIC_AGENT_LLM_PROVIDER", "")
        self.LOGIC_AGENT_LLM_MODEL = os.getenv("LOGIC_AGENT_LLM_MODEL", "")
        self.LOGIC_AGENT_LLM_BASE_URL = os.getenv("LOGIC_AGENT_LLM_BASE_URL", "")
        self.LOGIC_AGENT_LLM_API_KEY = os.getenv("LOGIC_AGENT_LLM_API_KEY", "")

        self.PERFORMANCE_AGENT_LLM_PROVIDER = os.getenv("PERFORMANCE_AGENT_LLM_PROVIDER", "")
        self.PERFORMANCE_AGENT_LLM_MODEL = os.getenv("PERFORMANCE_AGENT_LLM_MODEL", "")
        self.PERFORMANCE_AGENT_LLM_BASE_URL = os.getenv("PERFORMANCE_AGENT_LLM_BASE_URL", "")
        self.PERFORMANCE_AGENT_LLM_API_KEY = os.getenv("PERFORMANCE_AGENT_LLM_API_KEY", "")

        self.AGGREGATOR_LLM_PROVIDER = os.getenv("AGGREGATOR_LLM_PROVIDER", "")
        self.AGGREGATOR_LLM_MODEL = os.getenv("AGGREGATOR_LLM_MODEL", "")
        self.AGGREGATOR_LLM_BASE_URL = os.getenv("AGGREGATOR_LLM_BASE_URL", "")
        self.AGGREGATOR_LLM_API_KEY = os.getenv("AGGREGATOR_LLM_API_KEY", "")

        self.GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
        self.DATABASE_URL = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/codereview",
        )
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        self.MAX_PARALLEL_AGENTS = _get_int("MAX_PARALLEL_AGENTS", 5)
        self.AGENT_TIMEOUT_SECONDS = _get_int("AGENT_TIMEOUT_SECONDS", 30)
        self.USE_LANGGRAPH = _get_bool("USE_LANGGRAPH", False)

        self.ENABLE_PR_COMMENT = _get_bool("ENABLE_PR_COMMENT", False)
        self.ENABLE_INLINE_COMMENT = _get_bool("ENABLE_INLINE_COMMENT", False)

        self.ENABLE_DEDUP_CACHE = _get_bool("ENABLE_DEDUP_CACHE", True)
        self.DEDUP_CACHE_TTL = _get_int("DEDUP_CACHE_TTL", 86_400)

        self.GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

        self.ENABLE_NOTIFY = _get_bool("ENABLE_NOTIFY", False)
        self.SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
        self.WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL", "")
        self.NOTIFY_ON_SEVERITIES = os.getenv("NOTIFY_ON_SEVERITIES", "CRITICAL,HIGH")

    def get_llm_config(
        self,
        component: Literal[
            "STYLE_AGENT",
            "SECURITY_AGENT",
            "LOGIC_AGENT",
            "PERFORMANCE_AGENT",
            "AGGREGATOR",
        ],
    ) -> LLMConfig:
        provider = getattr(self, f"{component}_LLM_PROVIDER") or self.LLM_PROVIDER
        model = getattr(self, f"{component}_LLM_MODEL") or self.LLM_MODEL
        base_url = getattr(self, f"{component}_LLM_BASE_URL") or self.LLM_BASE_URL
        api_key = getattr(self, f"{component}_LLM_API_KEY") or self._default_api_key_for_provider(provider)
        return LLMConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    def _default_api_key_for_provider(self, provider: str) -> str:
        name = provider.lower()
        if self.LLM_API_KEY:
            return self.LLM_API_KEY
        if name == "anthropic":
            return self.ANTHROPIC_API_KEY
        if name in {
            "openai",
            "azure",
            "deepseek",
            "groq",
            "openrouter",
            "ollama",
            "dashscope",
            "qwenapi",
            "qwencloud",
        }:
            return self.OPENAI_API_KEY
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
