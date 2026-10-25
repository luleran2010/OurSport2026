import base64
import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest
from pydantic import BaseModel

from app.core.llm import providers
from app.core.llm.types import InvalidOutput, ProviderError


class Draft(BaseModel):
    en: str


class Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


async def test_ollama_sends_schema_and_parses_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_seen = None

    def fake_urlopen(request: Any, timeout: float) -> Response:
        nonlocal request_seen
        request_seen = request
        assert timeout == 8
        return Response(
            {
                "model": "qwen3.5:9b",
                "message": {"content": '{"en":"Goal! Blue take the lead, 1-0."}'},
                "prompt_eval_count": 42,
                "eval_count": 13,
            }
        )

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = providers.OllamaProvider("http://localhost:11434/")

    response = await provider.complete(
        model="qwen3.5:9b",
        system="Only use the given facts.",
        prompt="Goal for Blue. Score 1-0.",
        output=Draft,
        timeout_s=8,
        images=[("image/jpeg", b"test-image")],
    )

    assert request_seen is not None
    body = json.loads(request_seen.data)
    assert request_seen.full_url == "http://localhost:11434/api/chat"
    assert body["format"] == Draft.model_json_schema()
    assert body["think"] is False
    assert body["messages"][1]["images"] == [base64.b64encode(b"test-image").decode()]
    assert response.parsed == Draft(en="Goal! Blue take the lead, 1-0.")
    assert (response.input_tokens, response.output_tokens) == (42, 13)


async def test_ollama_http_errors_preserve_retryability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_urlopen(*_: object, **__: object) -> None:
        raise HTTPError(
            "http://localhost:11434/api/chat",
            503,
            "service unavailable",
            None,
            BytesIO(b"starting"),
        )

    monkeypatch.setattr(providers, "urlopen", fail_urlopen)

    with pytest.raises(ProviderError, match="HTTP 503") as error:
        await providers.OllamaProvider("http://localhost:11434").complete(
            model="qwen3.5:9b",
            system="",
            prompt="",
            output=Draft,
            timeout_s=1,
        )

    assert error.value.retryable


async def test_ollama_rejects_output_that_does_not_match_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        providers,
        "urlopen",
        lambda *_args, **_kwargs: Response({"message": {"content": '{"fi":"maali"}'}}),
    )

    with pytest.raises(InvalidOutput):
        await providers.OllamaProvider("http://localhost:11434").complete(
            model="qwen3.5:9b",
            system="",
            prompt="",
            output=Draft,
            timeout_s=1,
        )


async def test_deepseek_sends_json_schema_and_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_seen = None

    def fake_urlopen(request: Any, timeout: float) -> Response:
        nonlocal request_seen
        request_seen = request
        assert timeout == 12
        return Response(
            {
                "model": "deepseek-chat",
                "choices": [
                    {"message": {"content": '{"en":"Pinewood win 4-2."}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 24, "completion_tokens": 9},
            }
        )

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    response = await providers.DeepSeekProvider("test-secret").complete(
        model="deepseek-chat",
        system="Write a match report.",
        prompt="Use verified facts only.",
        output=Draft,
        timeout_s=12,
    )

    assert request_seen is not None
    body = json.loads(request_seen.data)
    assert request_seen.full_url == "https://api.deepseek.com/chat/completions"
    assert request_seen.get_header("Authorization") == "Bearer test-secret"
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON schema" in body["messages"][0]["content"]
    assert Draft.model_json_schema() == json.loads(
        body["messages"][0]["content"].split("JSON schema: ", 1)[1]
    )
    assert response.parsed == Draft(en="Pinewood win 4-2.")
    assert (response.input_tokens, response.output_tokens) == (24, 9)


async def test_deepseek_rejects_image_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_urlopen(*_: object, **__: object) -> None:
        raise AssertionError("image requests must not be sent")

    monkeypatch.setattr(providers, "urlopen", unexpected_urlopen)

    with pytest.raises(ProviderError, match="does not support image"):
        await providers.DeepSeekProvider("test-secret").complete(
            model="deepseek-chat",
            system="",
            prompt="",
            output=Draft,
            timeout_s=1,
            images=[("image/png", b"image")],
        )


async def test_deepseek_http_errors_preserve_retryability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_urlopen(*_: object, **__: object) -> None:
        raise HTTPError(
            "https://api.deepseek.com/chat/completions",
            401,
            "unauthorized",
            None,
            BytesIO(b"invalid key"),
        )

    monkeypatch.setattr(providers, "urlopen", fail_urlopen)

    with pytest.raises(ProviderError, match="HTTP 401") as error:
        await providers.DeepSeekProvider("bad-key").complete(
            model="deepseek-chat",
            system="",
            prompt="",
            output=Draft,
            timeout_s=1,
        )

    assert not error.value.retryable
