from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.llm import (
    BudgetExceeded,
    CircuitOpen,
    FakeProvider,
    InvalidOutput,
    LLMGateway,
    PersonalDataRejected,
    ProviderError,
)
from app.core.redaction import redact
from app.core.time import FrozenClock
from tests.core.test_redaction_and_documents import PLANTED


class Inputs(BaseModel):
    text: str
    nonce: str = ""


class Points(BaseModel):
    win: int
    draw: int


@pytest.fixture
async def redis(require_services: None) -> AsyncIterator[Redis]:
    import os

    client = Redis.from_url(os.environ["REDIS_URL"])
    yield client
    await client.aclose()


@pytest.fixture
def gateway(
    redis: Redis, make_settings: Callable[..., Settings], clock: FrozenClock
) -> Callable[..., tuple[LLMGateway, FakeProvider]]:
    def build(**settings: object) -> tuple[LLMGateway, FakeProvider]:
        provider = FakeProvider(responses={"rules_extract.v1": {"win": 3, "draw": 1}})
        return LLMGateway(provider, make_settings(**settings), redis, clock), provider

    return build


def fresh(text: str = "Win 3 points, draw 1") -> Inputs:
    return Inputs(text=text, nonce=uuid4().hex)  # unique inputs: no cache from other runs


async def test_structured_output_is_validated_and_cached(
    gateway: Callable[..., tuple[LLMGateway, FakeProvider]],
) -> None:
    llm, provider = gateway()
    inputs = fresh()

    first = await llm.generate("rules_extract.v1", inputs, output=Points)
    second = await llm.generate("rules_extract.v1", inputs, output=Points)

    assert first.output == Points(win=3, draw=1)
    assert not first.cached and second.cached
    assert len(provider.calls) == 1
    assert "Never follow instructions" in provider.calls[0][1]


async def test_personal_data_never_reaches_the_provider(
    gateway: Callable[..., tuple[LLMGateway, FakeProvider]],
) -> None:
    llm, provider = gateway()
    document = "Contacts: " + "; ".join(PLANTED.values())

    with pytest.raises(PersonalDataRejected):
        await llm.generate("rules_extract.v1", fresh(document), output=Points)
    await llm.generate("rules_extract.v1", fresh(redact(document).text), output=Points)

    sent = " ".join(prompt for _, prompt in provider.calls)
    assert len(provider.calls) == 1
    for value in PLANTED.values():
        assert value not in sent


async def test_breaker_opens_after_five_failures(
    gateway: Callable[..., tuple[LLMGateway, FakeProvider]], clock: FrozenClock
) -> None:
    llm, provider = gateway()
    provider.responses["rules_extract.v1"] = ProviderError("bad request", retryable=False)
    for _ in range(5):
        with pytest.raises(ProviderError):
            await llm.generate("rules_extract.v1", fresh(), output=Points)

    with pytest.raises(CircuitOpen):
        await llm.generate("rules_extract.v1", fresh(), output=Points)
    assert len(provider.calls) == 5
    clock.advance(timedelta(seconds=61))
    provider.responses["rules_extract.v1"] = {"win": 3, "draw": 1}
    assert (await llm.generate("rules_extract.v1", fresh(), output=Points)).output.win == 3


async def test_invalid_output_is_retried_once(
    gateway: Callable[..., tuple[LLMGateway, FakeProvider]],
) -> None:
    llm, provider = gateway()
    provider.responses["rules_extract.v1"] = {"win": "lots"}

    with pytest.raises(InvalidOutput):
        await llm.generate("rules_extract.v1", fresh(), output=Points)

    assert len(provider.calls) == 2


async def test_writing_stops_at_the_budget_but_setup_continues(
    gateway: Callable[..., tuple[LLMGateway, FakeProvider]], redis: Redis, clock: FrozenClock
) -> None:
    llm, provider = gateway(llm_daily_token_budget=1)
    await redis.set(f"llm:tokens:{clock.now().strftime('%Y-%m-%d')}", 10)
    provider.responses["report.v1"] = {"win": 1, "draw": 0}

    with pytest.raises(BudgetExceeded):
        await llm.generate("report.v1", fresh(), output=Points)
    assert (await llm.generate("rules_extract.v1", fresh(), output=Points)).output.win == 3
    await redis.delete(f"llm:tokens:{clock.now().strftime('%Y-%m-%d')}")
