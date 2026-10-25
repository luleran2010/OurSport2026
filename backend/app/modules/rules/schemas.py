"""Rules API schemas."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Language = Literal["fi", "en", "bn"]


class RulesSummary(BaseModel):
    tournament_id: UUID
    version: int
    language: Language
    lines: list[str]


class WorkedExample(BaseModel):
    kind: Literal["worked_example", "edge_case"]
    title: str
    input: dict[str, object]
    expected: dict[str, object]
    passed: bool


class RuleConfigOut(BaseModel):
    id: UUID
    tournament_id: UUID
    version: int
    status: str
    config: dict[str, object]
