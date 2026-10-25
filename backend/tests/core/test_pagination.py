import base64
import json
from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    PageParams,
    decode_cursor,
    encode_cursor,
    page_params,
)
from app.main import create_app

cursor_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)
positions = st.dictionaries(st.text(min_size=1, max_size=20), cursor_values, max_size=4)


@given(positions)
def test_cursor_round_trips(position: dict[str, object]) -> None:
    assert decode_cursor(encode_cursor(position)) == position  # type: ignore[arg-type]  # Hypothesis draws a looser type than the cursor accepts


def test_cursor_is_url_safe_and_opaque() -> None:
    cursor = encode_cursor({"starts_at": "2026-10-24T14:00:00Z", "id": "0192-abc"})

    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _b64(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "not a cursor!",
        "",
        _b64([1, 2, 3]),
        _b64({"v": 99, "p": {"id": "x"}}),
        _b64({"v": 1, "p": ["id"]}),
        _b64({"v": 1, "p": {"id": {"nested": True}}}),
        _b64({"v": 1}),
        "A" * 2000,
    ],
    ids=[
        "garbage",
        "empty",
        "not-object",
        "unknown-version",
        "position-not-object",
        "nested-value",
        "missing-position",
        "too-long",
    ],
)
def test_invalid_cursor_is_validation_error(cursor: str) -> None:
    with pytest.raises(ValidationFailed) as caught:
        decode_cursor(cursor)

    assert caught.value.errors[0].field == "query.cursor"


@pytest.fixture
def client(make_settings: Callable[..., Settings]) -> TestClient:
    app = create_app(make_settings())

    @app.get("/things", response_model=Page[int])
    async def things(params: Annotated[PageParams, Depends(page_params)]) -> Page[int]:
        return Page(items=list(range(params.limit)), next_cursor=params.cursor)

    return TestClient(app)


def test_limit_defaults_to_twenty(client: TestClient) -> None:
    body = client.get("/things").json()

    assert len(body["items"]) == DEFAULT_LIMIT
    assert body["next_cursor"] is None


@pytest.mark.parametrize("limit", [0, MAX_LIMIT + 1])
def test_limit_out_of_range_is_rejected(client: TestClient, limit: int) -> None:
    response = client.get("/things", params={"limit": limit})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "query.limit"


def test_max_limit_is_allowed(client: TestClient) -> None:
    body = client.get("/things", params={"limit": MAX_LIMIT}).json()

    assert len(body["items"]) == MAX_LIMIT
