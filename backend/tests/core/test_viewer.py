from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import AccessClaims, decode_access_token, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE, Viewer, current_viewer

SECRET = "test-secret-not-for-real-use-0123456789abcdef"
NOW = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def claims(minutes: int = 15) -> AccessClaims:
    return AccessClaims(uuid4(), uuid4(), frozenset({"editor"}), NOW + timedelta(minutes=minutes))


def test_access_token_round_trip_and_expiry_follow_the_clock() -> None:
    token = encode_access_token(claims(), SECRET)

    decoded = decode_access_token(token, SECRET, NOW)

    assert decoded is not None and decoded.roles == frozenset({"editor"})
    assert decode_access_token(token, SECRET, NOW + timedelta(minutes=15)) is None
    assert decode_access_token(token, "another-secret-of-at-least-32-bytes-long", NOW) is None
    assert decode_access_token("not-a-jwt", SECRET, NOW) is None


def test_viewer_is_user_pass_or_anonymous(make_settings: Callable[..., Settings]) -> None:
    app = FastAPI()
    app.state.settings = make_settings()
    app.state.clock = FrozenClock(NOW)

    @app.get("/who")
    def who(viewer: Annotated[Viewer, Depends(current_viewer)]) -> dict[str, object]:
        return {"member": viewer.is_member, "pass": viewer.pass_token}

    client = TestClient(app)
    anonymous = client.get("/who").json()
    with_pass = client.get("/who", headers={"Authorization": "Pass abc123"}).json()
    client.cookies.set(ACCESS_COOKIE, encode_access_token(claims(), SECRET))
    member = client.get("/who").json()

    assert anonymous == {"member": False, "pass": None}
    assert with_pass == {"member": False, "pass": "abc123"}
    assert member == {"member": True, "pass": None}
