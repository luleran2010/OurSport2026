"""Model providers behind one interface. The only module importing a provider SDK."""

import asyncio
import base64
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.llm.types import InvalidOutput, ProviderError, ProviderResponse

type Image = tuple[str, bytes]  # (media type, bytes), e.g. a photo of a team list


class LLMProvider(Protocol):
    name: str

    async def complete[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output: type[T],
        timeout_s: float,
        images: Sequence[Image] = (),
    ) -> ProviderResponse[T]: ...


class AnthropicProvider:
    """Claude via the official SDK; structured output parsed into the Pydantic model."""

    name = "anthropic"

    def __init__(self, api_key: str | None) -> None:
        # Retries are the gateway's job (per-task policy), so the SDK makes one attempt.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def complete[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output: type[T],
        timeout_s: float,
        images: Sequence[Image] = (),
    ) -> ProviderResponse[T]:
        content: list[Any] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.standard_b64encode(data).decode(),
                },
            }
            for mime, data in images
        ]
        content.append({"type": "text", "text": prompt})
        try:
            response = await self._client.messages.parse(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=output,
                timeout=timeout_s,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(str(exc), retryable=exc.status_code >= 500) from exc
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise InvalidOutput(f"no usable output (stop_reason={response.stop_reason})")
        return ProviderResponse(
            parsed=response.parsed_output,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class DeepSeekProvider:
    """DeepSeek's OpenAI-compatible chat completions API with validated JSON output."""

    name = "deepseek"
    _URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def complete[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output: type[T],
        timeout_s: float,
        images: Sequence[Image] = (),
    ) -> ProviderResponse[T]:
        if images:
            raise ProviderError("DeepSeek chat does not support image inputs", retryable=False)
        schema = json.dumps(output.model_json_schema(), ensure_ascii=False)
        body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system}\n\nReturn valid JSON matching this JSON schema: {schema}"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        request = Request(
            self._URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        def send() -> dict[str, Any]:
            try:
                with urlopen(request, timeout=timeout_s) as response:
                    result: Any = json.loads(response.read())
            except HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(
                    f"DeepSeek returned HTTP {exc.code}: {message}",
                    retryable=exc.code == 429 or exc.code >= 500,
                ) from exc
            except (TimeoutError, URLError) as exc:
                raise ProviderError(f"DeepSeek request failed: {exc}", retryable=True) from exc
            except ValueError as exc:
                raise InvalidOutput(f"DeepSeek returned invalid JSON: {exc}") from exc
            if not isinstance(result, dict):
                raise ProviderError("DeepSeek returned a non-object response", retryable=False)
            return result

        response = await asyncio.to_thread(send)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise InvalidOutput("DeepSeek response has no chat completion")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise InvalidOutput("DeepSeek response has no message content")
        try:
            parsed = output.model_validate_json(message["content"])
        except (ValidationError, ValueError) as exc:
            raise InvalidOutput(str(exc)) from exc
        usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return ProviderResponse(
            parsed=parsed,
            model=str(response.get("model", model)),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


class OllamaProvider:
    """Local Ollama chat API with schema-constrained JSON output."""

    name = "ollama"

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url.rstrip('/')}/api/chat"

    async def complete[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output: type[T],
        timeout_s: float,
        images: Sequence[Image] = (),
    ) -> ProviderResponse[T]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(data).decode("ascii") for _, data in images],
                },
            ],
            "format": output.model_json_schema(),
            "think": False,
            "stream": False,
        }
        request = Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        def send() -> dict[str, Any]:
            try:
                with urlopen(request, timeout=timeout_s) as response:
                    result: Any = json.loads(response.read())
            except HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(
                    f"Ollama returned HTTP {exc.code}: {message}",
                    retryable=exc.code == 429 or exc.code >= 500,
                ) from exc
            except (TimeoutError, URLError) as exc:
                raise ProviderError(f"Ollama request failed: {exc}", retryable=True) from exc
            except ValueError as exc:
                raise InvalidOutput(f"Ollama returned invalid JSON: {exc}") from exc
            if not isinstance(result, dict):
                raise ProviderError("Ollama returned a non-object response", retryable=False)
            return result

        response = await asyncio.to_thread(send)
        message = response.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise InvalidOutput("Ollama response has no message content")
        try:
            parsed = output.model_validate_json(message["content"])
        except (ValidationError, ValueError) as exc:
            raise InvalidOutput(str(exc)) from exc
        return ProviderResponse(
            parsed=parsed,
            model=str(response.get("model", model)),
            input_tokens=int(response.get("prompt_eval_count", 0)),
            output_tokens=int(response.get("eval_count", 0)),
        )


type FakeResponder = Callable[[str, str], Any]  # (task, prompt) -> dict / model / Exception


@dataclass
class FakeProvider:
    """Deterministic provider for tests and local development (LLM_PROVIDER=fake).

    `responses` maps a task name to a dict (validated into the output model), a callable
    `(task, prompt)`, or an exception to raise. Every prompt sent is recorded in `calls`.
    """

    responses: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    name: str = "fake"

    async def complete[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output: type[T],
        timeout_s: float,
        images: Sequence[Image] = (),
    ) -> ProviderResponse[T]:
        task = model.removeprefix("fake:")
        self.calls.append((task, system + "\n" + prompt))
        response = self.responses.get(task, {})
        if callable(response):
            response = response(task, prompt)
        if isinstance(response, Exception):
            raise response
        try:
            parsed = output.model_validate(response)
        except ValidationError as exc:
            raise InvalidOutput(str(exc)) from exc
        return ProviderResponse(parsed, "fake", len(prompt) // 4, 50)
