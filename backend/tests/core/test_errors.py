from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import errors
from app.core.config import Settings
from app.core.errors import DomainError, FieldError, RateLimited
from app.main import create_app

# The contract from docs/05-api.md: every standard code and the status it maps to.
EXPECTED_STATUS = {
    "not_authenticated": 401,
    "forbidden": 403,
    "premium_required": 402,
    "not_found": 404,
    "validation_error": 422,
    "stale_version": 409,
    "conflict": 409,
    "seat_limit_reached": 409,
    "invite_expired": 409,
    "rules_not_confirmed": 409,
    "setup_not_ready": 409,
    "open_questions_remaining": 409,
    "draw_infeasible": 422,
    "schedule_infeasible": 422,
    "processing_agreement_required": 409,
    "filming_not_permitted": 409,
    "match_not_live": 409,
    "scorer_not_assigned": 403,
    "pass_revoked": 401,
    "pass_not_yet_valid": 401,
    "rate_limited": 429,
    "upstream_unavailable": 503,
}

ERROR_CLASSES = DomainError.__subclasses__()


def _client_raising(make_settings: Callable[..., Settings], exc: Exception) -> TestClient:
    app: FastAPI = create_app(make_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_every_standard_code_has_exactly_one_error_class() -> None:
    codes = [cls.code for cls in ERROR_CLASSES]

    assert sorted(codes) == sorted(EXPECTED_STATUS)


@pytest.mark.parametrize("error_class", ERROR_CLASSES, ids=lambda cls: cls.code)
def test_domain_error_maps_to_problem_details(
    error_class: type[DomainError], make_settings: Callable[..., Settings]
) -> None:
    exc = RateLimited(30) if error_class is RateLimited else error_class("Something specific")
    client = _client_raising(make_settings, exc)

    response = client.get("/boom")

    assert response.status_code == EXPECTED_STATUS[error_class.code]
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == error_class.code
    assert body["status"] == response.status_code
    assert body["type"] == f"/problems/{error_class.code}"
    assert body["title"] == error_class.title
    assert body["errors"] == []


def test_field_errors_are_returned(make_settings: Callable[..., Settings]) -> None:
    exc = errors.ValidationFailed(
        "Bad team list", errors=[FieldError(field="teams.3.name", message="empty name")]
    )
    client = _client_raising(make_settings, exc)

    body = client.get("/boom").json()

    assert body["detail"] == "Bad team list"
    assert body["errors"] == [{"field": "teams.3.name", "message": "empty name"}]


def test_rate_limited_sets_retry_after(make_settings: Callable[..., Settings]) -> None:
    client = _client_raising(make_settings, RateLimited(42))

    response = client.get("/boom")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


def test_request_validation_becomes_validation_error(
    make_settings: Callable[..., Settings],
) -> None:
    app = create_app(make_settings())

    @app.get("/items")
    async def items(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = TestClient(app).get("/items", params={"limit": "many"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "query.limit"


def test_unknown_route_is_not_found_problem(make_settings: Callable[..., Settings]) -> None:
    response = TestClient(create_app(make_settings())).get("/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


def test_wrong_method_is_method_not_allowed_problem(
    make_settings: Callable[..., Settings],
) -> None:
    response = TestClient(create_app(make_settings())).post("/health/live")

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


def test_unexpected_exception_is_internal_error_without_details(
    make_settings: Callable[..., Settings],
) -> None:
    client = _client_raising(make_settings, RuntimeError("database password is hunter2"))

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "hunter2" not in response.text
