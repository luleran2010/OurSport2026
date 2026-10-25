"""Sign-up, magic links and sessions end to end, with mail delivered to Mailpit."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.time import FrozenClock
from app.core.viewer import CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE
from conftest import Mailpit

AUTH = "/api/v1/auth"
TEAM_ID = "0192f0c4-0000-7000-8000-000000000001"


def new_email() -> str:
    return f"fan-{uuid4().hex[:12]}@example.com"


def signup(api: TestClient, email: str, **overrides: Any) -> Any:
    body = {
        "email": email,
        "display_name": "Test Fan",
        "language": "bn",
        "time_zone": "Europe/Helsinki",
        "age_13_plus": True,
        "privacy_accepted": True,
        "follow": {"target_type": "team", "target_id": TEAM_ID},
    }
    body.update(overrides)
    return api.post(f"{AUTH}/signup", json=body)


def sign_in(api: TestClient, mailpit: Mailpit, email: str) -> dict[str, Any]:
    response = api.post(f"{AUTH}/magic-link/verify", json={"token": mailpit.latest_token(email)})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def set_cookie(client: TestClient, name: str, value: str, path: str = "/") -> None:
    """Replace a cookie in the client's jar (same client, so the same event loop)."""
    domain = next((c.domain for c in client.cookies.jar), "testserver.local")
    for cookie in [c for c in client.cookies.jar if c.name == name]:
        client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    client.cookies.set(name, value, domain=domain, path=path)


@pytest.fixture
def signed_up() -> Iterator[list[events.UserSignedUp]]:
    seen: list[events.UserSignedUp] = []

    async def record(_: AsyncSession, event: events.UserSignedUp) -> None:
        seen.append(event)

    events.subscribe(events.UserSignedUp, record)
    yield seen
    events.unsubscribe(events.UserSignedUp, record)


def test_account_is_created_only_when_the_link_is_opened(
    api: TestClient, mailpit: Mailpit, signed_up: list[events.UserSignedUp]
) -> None:
    email = new_email()

    assert signup(api, email).status_code == 202
    assert api.get("/api/v1/me").status_code == 401
    assert signed_up == []

    session = sign_in(api, mailpit, email)

    assert session["account_created"] is True
    me = api.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Test Fan"
    assert me.json()["language"] == "bn"
    assert [str(e.user_id) for e in signed_up] == [session["user_id"]]
    assert signed_up[0].follow_target == {"target_type": "team", "target_id": TEAM_ID}


def test_signup_for_an_existing_email_sends_a_login_link(api: TestClient, mailpit: Mailpit) -> None:
    email = new_email()
    signup(api, email)
    first = sign_in(api, mailpit, email)

    again = signup(api, email, display_name="Someone Else")
    second = sign_in(api, mailpit, email)

    assert again.status_code == 202
    assert second["account_created"] is False
    assert second["user_id"] == first["user_id"]
    assert api.get("/api/v1/me").json()["display_name"] == "Test Fan"


def test_magic_link_for_unknown_email_is_accepted_but_sends_nothing(
    api: TestClient, mailpit: Mailpit
) -> None:
    email = new_email()

    response = api.post(f"{AUTH}/magic-link", json={"email": email})

    assert response.status_code == 202
    assert mailpit.messages_to(email) == []


def test_links_are_single_use_and_expire(
    api: TestClient, mailpit: Mailpit, clock: FrozenClock
) -> None:
    email = new_email()
    signup(api, email)
    token = mailpit.latest_token(email)
    assert api.post(f"{AUTH}/magic-link/verify", json={"token": token}).status_code == 200

    reused = api.post(f"{AUTH}/magic-link/verify", json={"token": token})
    api.post(f"{AUTH}/magic-link", json={"email": email})
    late = mailpit.latest_token(email)
    clock.advance(timedelta(minutes=16))
    expired = api.post(f"{AUTH}/magic-link/verify", json={"token": late})

    assert reused.status_code == 401
    assert expired.status_code == 401
    assert expired.json()["code"] == "not_authenticated"


def test_refresh_rotates_and_a_reused_token_revokes_the_session(
    api: TestClient, mailpit: Mailpit
) -> None:
    email = new_email()
    signup(api, email)
    session = sign_in(api, mailpit, email)
    old_refresh = api.cookies.get(REFRESH_COOKIE)

    rotated = api.post(f"{AUTH}/refresh", headers={CSRF_HEADER: session["csrf_token"]})
    assert rotated.status_code == 200
    new_csrf = rotated.json()["csrf_token"]
    assert api.cookies.get(REFRESH_COOKIE) != old_refresh

    new_refresh = api.cookies.get(REFRESH_COOKIE) or ""
    set_cookie(api, REFRESH_COOKIE, old_refresh or "", AUTH)  # someone replays the old token
    replayed = api.post(f"{AUTH}/refresh", headers={CSRF_HEADER: new_csrf})
    set_cookie(api, REFRESH_COOKIE, new_refresh, AUTH)
    after = api.post(f"{AUTH}/refresh", headers={CSRF_HEADER: new_csrf})

    assert replayed.status_code == 401
    assert after.status_code == 401


def test_unsafe_requests_need_the_csrf_header(api: TestClient, mailpit: Mailpit) -> None:
    email = new_email()
    signup(api, email)
    session = sign_in(api, mailpit, email)

    denied = api.patch("/api/v1/me", json={"display_name": "Changed"})
    allowed = api.patch(
        "/api/v1/me",
        json={"display_name": "Changed", "language": "fi"},
        headers={CSRF_HEADER: session["csrf_token"]},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == "Changed"
    assert allowed.json()["language"] == "fi"


def test_logout_ends_the_session(api: TestClient, mailpit: Mailpit) -> None:
    email = new_email()
    signup(api, email)
    session = sign_in(api, mailpit, email)
    refresh_token = api.cookies.get(REFRESH_COOKIE)

    out = api.post(f"{AUTH}/logout", headers={CSRF_HEADER: session["csrf_token"]})
    me = api.get("/api/v1/me")
    set_cookie(api, REFRESH_COOKIE, refresh_token or "", AUTH)
    set_cookie(api, CSRF_COOKIE, "x")
    replayed = api.post(f"{AUTH}/refresh", headers={CSRF_HEADER: "x"})

    assert out.status_code == 204
    assert me.status_code == 401
    assert replayed.status_code == 401


def test_logout_needs_a_signed_in_user(api: TestClient) -> None:
    assert api.post(f"{AUTH}/logout").status_code == 401


def test_too_many_links_for_one_email_are_rate_limited(api: TestClient) -> None:
    email = new_email()

    codes = [api.post(f"{AUTH}/magic-link", json={"email": email}).status_code for _ in range(6)]
    limited = api.post(f"{AUTH}/magic-link", json={"email": email})

    assert codes == [202] * 5 + [429]
    assert limited.json()["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


@pytest.mark.parametrize(
    "override",
    [{"age_13_plus": False}, {"privacy_accepted": False}, {"time_zone": "Mars/Base"}],
)
def test_signup_requires_age_privacy_and_a_real_time_zone(
    api: TestClient, override: dict[str, Any]
) -> None:
    response = signup(api, new_email(), **override)

    assert response.status_code == 422
