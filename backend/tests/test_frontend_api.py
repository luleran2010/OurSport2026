"""The endpoints the web front end needs (T-066): catalogue lists, search, players, match
feeds, stories, paged notifications, `Me` parts, demo sign-in and the scoring console."""

import datetime as dt
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessClaims, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import PlayerCreate
from app.modules.scoring import service as scoring

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
SECRET = "test-secret-not-for-real-use-0123456789abcdef"


def sign_in(api: TestClient, clock: FrozenClock, user_id: UUID) -> dict[str, str]:
    claims = AccessClaims(user_id, uuid4(), frozenset(), clock.now() + dt.timedelta(minutes=10))
    api.cookies.set(ACCESS_COOKIE, encode_access_token(claims, SECRET))
    api.cookies.set(CSRF_COOKIE, "csrf-test-token")
    return {CSRF_HEADER: "csrf-test-token"}


# --- catalogue -------------------------------------------------------------------------------


async def test_catalogue_lists_published_tournaments_teams_and_organisations(
    api: TestClient, published_cup: dict[str, Any]
) -> None:
    tid = str(published_cup["tournament_id"])

    org = api.get(f"/api/v1/tournaments/{tid}").json()["organisation_id"]
    sports = api.get("/api/v1/sports").json()
    # the test database is shared, so other tests' tournaments are listed too: filter or page
    tournaments = api.get(f"/api/v1/tournaments?organisation_id={org}").json()
    orgs, cursor = [], ""
    while True:
        page = api.get(f"/api/v1/organisations?limit=100{cursor}").json()
        orgs += page["items"]
        if not page["next_cursor"]:
            break
        cursor = f"&cursor={page['next_cursor']}"
    first = api.get(f"/api/v1/teams?tournament_id={tid}&limit=10").json()
    rest = api.get(f"/api/v1/teams?tournament_id={tid}&limit=10&cursor={first['next_cursor']}")

    assert any(s["code"] == "football" for s in sports)
    mine = next(t for t in tournaments["items"] if t["id"] == tid)
    assert mine["organisation_name"] == "Cup Org"
    assert mine["team_count"] == 16
    assert any(o["id"] == org and o["name"] == "Cup Org" for o in orgs)
    assert len({o["id"] for o in orgs}) == len(orgs)  # pages never repeat an organisation
    assert len(first["items"]) == 10 and first["next_cursor"]
    names = [t["name"] for t in first["items"] + rest.json()["items"]]
    assert len(names) == 16 and names == sorted(names)
    assert all(t["tournament_ids"] == [tid] for t in first["items"])
    assert "contact_email" not in first["items"][0]


async def test_catalogue_rejects_a_tampered_cursor(api: TestClient) -> None:
    response = api.get("/api/v1/teams?cursor=not-a-cursor")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_search_finds_teams_and_needs_two_letters(
    api: TestClient, published_cup: dict[str, Any]
) -> None:
    hits = api.get("/api/v1/search?q=Cup").json()["hits"]

    assert any(h["type"] == "tournament" for h in hits)
    assert api.get("/api/v1/search?q=a").status_code == 422


async def test_drafts_never_reach_the_catalogue(api: TestClient, db: AsyncSession) -> None:
    listed = {t["status"] for t in api.get("/api/v1/tournaments?limit=100").json()["items"]}

    assert "draft" not in listed


# --- matches, players, stories ---------------------------------------------------------------


async def test_the_match_feed_and_organisation_matches(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    org = (await competitions.get_tournament(db, Viewer(), tid)).organisation_id

    feed = api.get("/api/v1/matches").json()
    upcoming = api.get(f"/api/v1/organisations/{org}/matches?when=upcoming").json()

    ours = [m for m in feed["matches"] if m["tournament_id"] == str(tid)]
    assert len(ours) == 32
    assert ours[0]["sport"] == "football" and ours[0]["data_level"] == "events"
    assert feed["server_time"].endswith("Z") or "+00:00" in feed["server_time"]
    assert all(m["status"] == "scheduled" for m in upcoming["matches"])
    assert api.get(f"/api/v1/organisations/{uuid4()}/matches").status_code == 404


async def test_player_pages_follow_the_visibility_rules(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    team = (await competitions.entries_of(db, tid))[0].team_id
    shown = await competitions.add_roster_player(
        db, clock, owner, tid, team, PlayerCreate(display_name="Pat Public", shirt_number=9)
    )
    hidden = await competitions.add_roster_player(
        db,
        clock,
        owner,
        tid,
        team,
        PlayerCreate(display_name="Hana Hidden", shirt_number=4, visibility="hidden"),
    )

    page = api.get(f"/api/v1/players/{shown.id}")
    team_page = api.get(f"/api/v1/teams/{team}").json()

    assert page.status_code == 200 and page.json()["display_name"] == "Pat Public"
    assert api.get(f"/api/v1/players/{hidden.id}").status_code == 404
    assert [p["display_name"] for p in team_page["players"]] == ["Pat Public"]


async def test_story_lists_are_public_but_my_stories_need_a_member(
    api: TestClient, published_cup: dict[str, Any]
) -> None:
    public = api.get("/api/v1/stories")

    assert public.status_code == 200 and "next_cursor" in public.json()
    assert api.get("/api/v1/me/stories").status_code == 401


async def test_tables_carry_team_short_names_and_qualification_status(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)

    page = api.get(f"/api/v1/tournaments/{tid}").json()
    table = api.get(f"/api/v1/tournaments/{tid}/standings").json()["groups"][0]

    assert page["organisation_name"] == "Cup Org" and page["is_junior"] is False
    fmt = page["format"]
    assert fmt["kind"] == "groups_then_knockout" and fmt["qualify_per_group"] >= 1
    assert fmt["points"]["win"] == 3 and fmt["tiebreakers"][0] == "points"
    assert table["group_id"]
    assert {r["status"] for r in table["rows"]} <= {"through", "out", "alive"}


# --- me, follows, notifications, demo sign-in ------------------------------------------------


async def test_demo_login_fills_me_with_follows_and_staff_roles(
    api: TestClient, published_cup: dict[str, Any]
) -> None:
    session = api.post("/api/v1/auth/demo-login", json={"persona": "fan"})
    csrf = {CSRF_HEADER: session.json()["csrf_token"]}
    team = api.get(f"/api/v1/teams?tournament_id={published_cup['tournament_id']}").json()
    team_id = team["items"][0]["id"]

    followed = api.post(
        "/api/v1/me/follows",
        json={"target_type": "team", "target_id": team_id, "is_primary": True},
        headers=csrf,
    )
    me = api.get("/api/v1/me").json()
    notifications = api.get("/api/v1/me/notifications?limit=5").json()

    assert session.status_code == 200
    assert followed.status_code == 201
    assert followed.json()["target"]["name"] == team["items"][0]["name"]
    assert me["primary_team_id"] == team_id
    assert {
        "id": followed.json()["id"],
        "target_type": "team",
        "target_id": team_id,
        "is_primary": True,
    } in me["follows"]
    assert notifications == {"items": [], "next_cursor": None, "unread_count": 0}


async def test_demo_login_does_not_exist_outside_development(api: TestClient) -> None:
    settings = api.app.state.settings  # type: ignore[attr-defined]  # Starlette app state
    api.app.state.settings = settings.model_copy(update={"env": "staging"})  # type: ignore[attr-defined]
    try:
        response = api.post("/api/v1/auth/demo-login", json={"persona": "editor"})
    finally:
        api.app.state.settings = settings  # type: ignore[attr-defined]

    assert response.status_code == 404


async def test_me_lists_the_tournaments_an_organiser_runs(
    api: TestClient, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    sign_in(api, clock, published_cup["owner"])

    me = api.get("/api/v1/me").json()

    staff = me["staff_tournaments"]
    assert staff[0]["tournament_id"] == str(published_cup["tournament_id"])
    assert staff[0]["tournament_name"] == "Published Cup" and staff[0]["role"] == "owner"
    assert me["memberships"][0]["organisation_name"] == "Cup Org"


async def test_only_organisers_change_settings_and_staff(
    api: TestClient,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Any,
) -> None:
    tid = published_cup["tournament_id"]
    stranger = sign_in(api, clock, await make_user())
    denied = api.patch(
        f"/api/v1/tournaments/{tid}", json={"live_access": "members"}, headers=stranger
    )

    owner = sign_in(api, clock, published_cup["owner"])
    changed = api.patch(
        f"/api/v1/tournaments/{tid}", json={"live_access": "members"}, headers=owner
    )
    staff = api.get(f"/api/v1/tournaments/{tid}/staff")

    assert denied.status_code in (403, 404)
    assert changed.status_code == 200 and changed.json()["settings"]["live_access"] == "members"
    assert [s["role"] for s in staff.json()] == ["owner"]


# --- scoring console -------------------------------------------------------------------------


async def test_the_event_pad_lists_buttons_and_refuses_unknown_sports(api: TestClient) -> None:
    pad = api.get("/api/v1/sports/futsal/event-types").json()

    ids = {b["id"] for b in pad["buttons"]}
    assert {"goal", "own_goal", "shootout_scored", "foul", "timeout"} <= ids
    assert all(b["type"] in pad["event_types"] for b in pad["buttons"])
    assert api.get("/api/v1/sports/cricket/event-types").status_code == 422


async def test_a_scorer_pass_reads_the_console_state(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(KICK_OFF)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    passes = await scoring.list_passes(db, published_cup["settings"], owner, tid)
    token = passes[0].token
    pass_header = {"Authorization": f"Pass {token}"}

    mine = api.get("/api/v1/scoring/me", headers=pass_header).json()
    match_id = next(m["match_id"] for m in mine if m["home"])
    api.post(f"/api/v1/matches/{match_id}/start", headers=pass_header)
    api.post(
        f"/api/v1/matches/{match_id}/events",
        json={"client_seq": 1, "type": "period_start", "payload": {"period": 1}},
        headers=pass_header,
    )
    home = next(m for m in mine if m["match_id"] == match_id)["home"]["id"]
    api.post(
        f"/api/v1/matches/{match_id}/events",
        json={"client_seq": 2, "type": "goal", "team_id": home},
        headers=pass_header,
    )
    state = api.get(f"/api/v1/matches/{match_id}/scoring", headers=pass_header)
    anonymous = api.get(f"/api/v1/matches/{match_id}/scoring")

    assert mine[0]["tournament_name"] == "Published Cup" and mine[0]["pitch"]
    body = state.json()
    assert state.status_code == 200
    assert body["score"]["home_goals"] == 1 and body["period"] == 1
    assert body["last_client_seq"] == 2 and body["role"] == "scorer"
    assert [e["type"] for e in body["events"]] == ["goal", "period_start"]
    assert anonymous.status_code == 401


async def test_organisers_see_their_matches_to_score(
    api: TestClient, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    sign_in(api, clock, published_cup["owner"])

    mine = api.get("/api/v1/scoring/me").json()

    assert len(mine) == 32
    assert mine == sorted(mine, key=lambda m: m["starts_at"])


# --- setup list (publisher wizard) -------------------------------------------------------------


async def test_organisers_list_their_setups_to_resume_them(
    api: TestClient, clock: FrozenClock, published_cup: dict[str, Any], make_user: Any
) -> None:
    assert api.get("/api/v1/setup").status_code == 401
    sign_in(api, clock, await make_user())
    assert api.get("/api/v1/setup").json() == []

    sign_in(api, clock, published_cup["owner"])
    setups = api.get("/api/v1/setup").json()
    one = api.get(f"/api/v1/setup/{setups[0]['id']}").json()

    assert [s["tournament_id"] for s in setups] == [str(published_cup["tournament_id"])]
    assert setups[0]["status"] == "published"
    assert setups[0]["tournament"]["name"] == "Published Cup"
    assert one["tournament"]["is_junior"] is False and one["tournament"]["sport"] == "football"
    page = api.get(f"/api/v1/tournaments/{published_cup['tournament_id']}").json()
    assert one["tournament"]["organisation_id"] == page["organisation_id"]


async def test_organisers_remove_an_event_they_never_published(
    api: TestClient, clock: FrozenClock, published_cup: dict[str, Any], make_user: Any
) -> None:
    tid = published_cup["tournament_id"]
    owner = sign_in(api, clock, published_cup["owner"])
    org = api.get(f"/api/v1/tournaments/{tid}").json()["organisation_id"]
    draft = api.post(
        "/api/v1/setup", json={"organisation_id": org, "name": "Never Played Cup"}, headers=owner
    ).json()
    api.post(
        f"/api/v1/setup/{draft['id']}/files",
        data={"kind": "team_list", "text": "Northside Rovers\nLakeview United"},
        headers=owner,
    )
    published = next(s for s in api.get("/api/v1/setup").json() if s["status"] == "published")

    stranger = sign_in(api, clock, await make_user())
    denied = api.delete(f"/api/v1/setup/{draft['id']}", headers=stranger)
    owner = sign_in(api, clock, published_cup["owner"])
    kept = api.delete(f"/api/v1/setup/{published['id']}", headers=owner)
    removed = api.delete(f"/api/v1/setup/{draft['id']}", headers=owner)

    assert denied.status_code == 404
    assert kept.status_code == 409
    assert removed.status_code == 204
    assert api.get(f"/api/v1/setup/{draft['id']}").status_code == 404
    assert draft["id"] not in {s["id"] for s in api.get("/api/v1/setup").json()}
    assert api.get(f"/api/v1/tournaments/{tid}").status_code == 200


async def test_a_scorer_pass_before_the_tournament_days_says_when_it_works(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(KICK_OFF - dt.timedelta(days=30))
    owner = Viewer(user_id=published_cup["owner"])
    passes = await scoring.list_passes(
        db, published_cup["settings"], owner, published_cup["tournament_id"]
    )

    early = api.get("/api/v1/scoring/me", headers={"Authorization": f"Pass {passes[0].token}"})

    assert early.status_code == 401 and early.json()["code"] == "pass_not_yet_valid"
    assert passes[0].valid_from <= KICK_OFF < passes[0].valid_until
