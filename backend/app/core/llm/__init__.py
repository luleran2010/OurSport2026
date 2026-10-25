"""LLM gateway: the only place that talks to a model provider (CLAUDE.md rule 4)."""

from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.llm.gateway import LLMGateway, task_kind
from app.core.llm.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    FakeProvider,
    LLMProvider,
    OllamaProvider,
)
from app.core.llm.types import (
    BudgetExceeded,
    CircuitOpen,
    InvalidOutput,
    LLMError,
    LLMResult,
    PersonalDataRejected,
    ProviderError,
)
from app.core.time import Clock

__all__ = [
    "BudgetExceeded",
    "CircuitOpen",
    "FakeProvider",
    "InvalidOutput",
    "LLMError",
    "LLMGateway",
    "LLMProvider",
    "LLMResult",
    "PersonalDataRejected",
    "ProviderError",
    "build_gateway",
    "get_llm",
    "task_kind",
]


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        return AnthropicProvider(key)
    if settings.llm_provider == "deepseek":
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=deepseek")
        return DeepSeekProvider(settings.llm_api_key.get_secret_value())
    if settings.llm_provider == "fake":
        return FakeProvider()
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings.llm_ollama_base_url)
    raise ValueError(f"unknown LLM_PROVIDER '{settings.llm_provider}'")


def build_gateway(
    settings: Settings, redis: Redis, clock: Clock, provider: LLMProvider | None = None
) -> LLMGateway:
    return LLMGateway(provider or build_provider(settings), settings, redis, clock)


def get_llm(request: Request) -> LLMGateway:
    """FastAPI dependency: the application's gateway."""
    gateway: LLMGateway = request.app.state.llm
    return gateway
