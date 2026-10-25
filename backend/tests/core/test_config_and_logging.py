import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

STRONG_SECRET = "s" * 40


def test_missing_required_settings_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_comma_separated_lists_are_parsed(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(
        cors_origins="https://oursport.example, http://localhost:3000",
        feature_flags="live_draw,streams",
    )

    assert settings.cors_origins == ["https://oursport.example", "http://localhost:3000"]
    assert settings.feature_enabled("live_draw")
    assert not settings.feature_enabled("billing")


@pytest.mark.parametrize("env", ["staging", "production"])
def test_placeholder_secret_is_rejected_outside_dev(
    make_settings: Callable[..., Settings], env: str
) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make_settings(env=env, jwt_secret="change-me-local-only", llm_provider="anthropic")


def test_fake_llm_is_rejected_in_production(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        make_settings(env="production", jwt_secret=STRONG_SECRET, llm_provider="fake")


def test_production_accepts_real_values(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(env="production", jwt_secret=STRONG_SECRET, llm_provider="anthropic")

    assert not settings.is_dev


def test_request_id_is_generated_and_returned(make_settings: Callable[..., Settings]) -> None:
    response = TestClient(create_app(make_settings())).get("/health/live")

    assert len(response.headers["x-request-id"]) == 36


def test_valid_incoming_request_id_is_kept(make_settings: Callable[..., Settings]) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health/live", headers={"X-Request-ID": "lb-7f3a.2"})

    assert response.headers["x-request-id"] == "lb-7f3a.2"


def test_unsafe_incoming_request_id_is_replaced(make_settings: Callable[..., Settings]) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health/live", headers={"X-Request-ID": "bad id\nInjected: yes"})

    assert response.headers["x-request-id"] != "bad id\nInjected: yes"
    assert len(response.headers["x-request-id"]) == 36


def test_request_is_logged_as_json_with_request_id(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health/live", headers={"X-Request-ID": "req-123"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    request_logs = [line for line in lines if line.get("event") == "request"]
    assert response.status_code == 200
    assert request_logs[-1] == {
        **request_logs[-1],
        "request_id": "req-123",
        "method": "GET",
        "path": "/health/live",
        "status": 200,
        "level": "info",
    }
