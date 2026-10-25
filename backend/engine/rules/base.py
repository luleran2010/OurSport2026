from pydantic import BaseModel, ConfigDict


class RuleModel(BaseModel):
    """Base for engine configuration models: immutable, unknown fields rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")
