from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

API_PREFIX = "/api/v1"

# Values shipped in .env.example; acceptable only where nothing real is at stake.
_PLACEHOLDER_SECRETS = {"change-me-local-only", "change-me", ""}
_MIN_SECRET_LENGTH = 32


def _split_comma_list(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Process configuration, read from the environment (and `.env` locally).

    Required settings have no default, so the app refuses to start without them.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    env: Environment = "local"

    database_url: str
    redis_url: str
    db_pool_size: int = 20  # per process; Postgres max_connections must cover every process
    db_max_overflow: int = 20
    redis_max_connections: int = 200
    redis_pool_timeout_s: float = 5.0
    shared_cache_enabled: bool = True  # anonymous public reads cached in Redis (≤ 30 s)

    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket: str = "oursport-local"
    s3_region: str = "eu-north-1"

    public_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"  # the front end; magic links point here
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    widget_embed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    jwt_secret: SecretStr
    cookie_domain: str = "localhost"
    magic_link_per_email_per_hour: int = Field(default=5, ge=1)
    magic_link_per_ip_per_hour: int = Field(default=20, ge=1)

    email_smtp_host: str = "localhost"
    email_smtp_port: int = 1025
    email_from: str = "OurSport <no-reply@oursport.local>"

    llm_provider: str = "fake"
    llm_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_ollama_base_url: str = "http://localhost:11434"
    llm_daily_token_budget: int = Field(default=2_000_000, ge=0)
    llm_tournament_token_budget: int = Field(default=300_000, ge=0)
    policy_catalogue_version: int = Field(default=1, ge=1)

    upload_max_mb: int = Field(default=10, ge=1)
    malware_scan_url: str | None = None

    sentry_dsn: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    feature_flags: Annotated[frozenset[str], NoDecode] = frozenset()

    health_check_timeout_s: float = Field(default=2.0, gt=0)
    live_ping_seconds: float = Field(default=25.0, gt=0)
    vapid_private_key: SecretStr | None = None  # web push; unset: in-app and email only
    vapid_subject: str = "mailto:no-reply@oursport.local"

    @field_validator("cors_origins", "widget_embed_origins", "feature_flags", mode="before")
    @classmethod
    def _parse_comma_lists(cls, value: object) -> object:
        return _split_comma_list(value)

    @model_validator(mode="after")
    def _require_real_secrets_outside_dev(self) -> "Settings":
        if self.env in ("staging", "production"):
            secret = self.jwt_secret.get_secret_value()
            if secret in _PLACEHOLDER_SECRETS or len(secret) < _MIN_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET must be a real secret of at least {_MIN_SECRET_LENGTH} "
                    f"characters in {self.env}"
                )
            if self.llm_provider == "fake":
                raise ValueError(f"LLM_PROVIDER=fake is not allowed in {self.env}")
        return self

    @property
    def is_dev(self) -> bool:
        return self.env in ("local", "test")

    def feature_enabled(self, flag: str) -> bool:
        return flag in self.feature_flags


@lru_cache
def get_settings() -> Settings:
    """Settings for this process, loaded and validated once."""
    return Settings()
