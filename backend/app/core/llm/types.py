"""Gateway types shared by callers and providers."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

TaskKind = Literal["extraction", "commentary", "explanation", "story"]


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    task: str  # "rules_extract.v1"
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool
    latency_ms: int


@dataclass(frozen=True)
class ProviderResponse[T: BaseModel]:
    parsed: T
    model: str
    input_tokens: int
    output_tokens: int


class LLMError(Exception):
    """The gateway could not produce a result; callers fall back (templates, guided form)."""


class ProviderError(LLMError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class InvalidOutput(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class PersonalDataRejected(LLMError):
    """Inputs still contain personal data after redaction; nothing was sent."""


class CircuitOpen(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass
