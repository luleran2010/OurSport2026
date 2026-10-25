"""The v1 contract served by the mock: auth and CSRF, catalogue, fan reads, follows,
notifications, scoring and the live socket (shapes are checked in test_contract.py)."""

import os

os.environ["OURSPORT_SIMULATE"] = "0"  # deterministic: no background ticker

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, store  # noqa: E402
from app.v1 import project  # noqa: E402
from app.v1.ids import uid  # noqa: E402

V1 = "/api/v1"


def setup_function():
    store.reset()
    project.LIVE_ACCESS.clear()


def _browser() -> TestClient:
    return TestClient(app)


def _demo(c: TestClient, persona: str = "fan") -> dict:
    r = c.post(f"{V1}/auth/demo-login", json={"persona": persona})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


# ---- auth ------------------------------------------------------------------------------------


def test_magic_link_sign_up_creates_the_account_and_follows_the_team():
    c = _browser()
    team = uid("team", "tarmo")
    body = {"email": "Aino@example.com", "display_name": "Aino K.", "language": "fi", "time_zone": "Europe/Helsinki",
            "age_13_plus": True, "privacy_accepted": True, "follow": {"target_type": "team", "target_id": team}}
    assert c.post(f"{V1}/auth/signup", json=body).status_code == 202
    assert c.get(f"{V1}/me").status_code == 401  # nothing until the link is opened
    token = c.get("/mock/outbox").json()[0]["token"]

    session = c.post(f"{V1}/auth/magic-link/verify", json={"token": token})
    me = c.get(f"{V1}/me").json()

    assert session.status_code == 200 and session.json()["account_created"] is True
    assert me["display_name"] == "Aino K." and me["language"] == "fi" and me["primary_team_id"] == team
    assert c.post(f"{V1}/auth/magic-link/verify", json={"token": token}).status_code == 401  # used once


def test_errors_are_problem_details():
    r = _browser().get(f"{V1}/me")

    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "not_authenticated" and r.json()["type"] == "/problems/not_authenticated"
    bad = _browser().post(f"{V1}/auth/demo-login", json={"persona": "wizard"})
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error" and bad.json()["errors"]


def test_unsafe_requests_need_the_csrf_header_and_refresh_rotates():
    c = _browser()
    csrf = _demo(c)
    follow = {"target_type": "team", "target_id": uid("team", "kko")}

    assert c.post(f"{V1}/me/follows", json=follow).status_code == 403
    assert c.post(f"{V1}/me/follows", json=follow, headers=csrf).status_code == 201
    old_refresh = c.cookies.get("oursport_refresh")
    rotated = c.post(f"{V1}/auth/refresh", headers=csrf)
    assert rotated.status_code == 200 and c.cookies.get("oursport_refresh") != old_refresh
    new_csrf = {"X-CSRF-Token": rotated.json()["csrf_token"]}
    assert c.post(f"{V1}/auth/logout", headers=new_csrf).status_code == 204
    assert c.get(f"{V1}/me").status_code == 401


def test_demo_personas():
    fan, organiser, editor = _browser(), _browser(), _browser()
    _demo(fan), _demo(organiser, "organiser"), _demo(editor, "editor")

    assert fan.get(f"{V1}/me").json()["plan"]["tier"] == "premium"
    staff = organiser.get(f"{V1}/me").json()["staff_tournaments"]
    assert {s["tournament_id"] for s in staff} == {uid("tournament", "njc-u17"), uid("tournament", "oulu-sixes")}
    assert editor.get(f"{V1}/me").json()["global_roles"] == ["editor"]


# ---- catalogue and fan reads -----------------------------------------------------------------


def test_catalogue_pages_and_ids():
    c = _browser()
    first = c.get(f"{V1}/teams", params={"limit": 5}).json()
    rest = c.get(f"{V1}/teams", params={"limit": 100, "cursor": first["next_cursor"]}).json()
    tournaments = c.get(f"{V1}/tournaments", params={"limit": 100}).json()["items"]

    assert len(first["items"]) == 5 and first["next_cursor"]
    assert len({t["id"] for t in first["items"] + rest["items"]}) == len(first["items"]) + len(rest["items"])
    assert {"football", "ice_hockey"} <= {s["code"] for s in c.get(f"{V1}/sports").json()}
    cup = next(t for t in tournaments if t["id"] == uid("tournament", "njc-u17"))
    assert cup["is_junior"] and cup["organisation_name"] == "OLS" and cup["team_count"] == 8
    assert c.get(f"{V1}/teams", params={"cursor": "garbage"}).json()["code"] == "validation_error"


def test_live_scores_follow_the_live_access_policy():
    guest, member = _browser(), _browser()
    _demo(member)
    live = uid("match", "njc5")
    assert guest.get(f"{V1}/matches/{live}").json()["match"]["score"]["home_goals"] == 1  # public by default
    project.LIVE_ACCESS["njc-u17"] = "members"

    assert guest.get(f"{V1}/matches/{live}").json()["match"]["score"] is None
    assert member.get(f"{V1}/matches/{live}").json()["match"]["score"]["home_goals"] == 1
    feed = member.get(f"{V1}/matches", params={"when": "live"}).json()
    assert feed["matches"] and all(m["status"] == "live" for m in feed["matches"])
    assert guest.get(f"{V1}/live/token", params={"match_id": live}).status_code == 401


def test_tournament_standings_scenarios_and_rules():
    c = _browser()
    tid = uid("tournament", "njc-u17")

    page = c.get(f"{V1}/tournaments/{tid}").json()
    table = c.get(f"{V1}/tournaments/{tid}/standings").json()["groups"][0]
    scenarios = c.get(f"{V1}/tournaments/{tid}/scenarios").json()
    rules = c.get(f"{V1}/tournaments/{tid}/rules/summary", params={"lang": "fi"}).json()

    assert [g["name"] for g in page["groups"]] == ["Group A", "Group B"]
    assert table["rows"][0]["position"] == 1 and table["rows"][0]["status"] in {"through", "out", "alive"}
    assert scenarios and scenarios[0]["scenario"]["status"] in {"clinched", "eliminated", "alive"}
    assert rules["language"] == "fi" and rules["lines"][0].startswith("Match length")


def test_hidden_juniors_never_appear():
    c = _browser()
    junior_team = c.get(f"{V1}/teams/{uid('team', 'olsu17')}").json()
    hits = c.get(f"{V1}/search", params={"q": "Veeti"}).json()["hits"]

    assert junior_team["players"] == []
    assert hits == []
    assert c.get(f"{V1}/players/{uid('player', 'pl4')}").status_code == 404
    guardian = _browser()
    _demo(guardian)  # the demo fan is Veeti's guardian
    assert guardian.get(f"{V1}/players/{uid('player', 'pl4')}").status_code == 200


# ---- follows and notifications ---------------------------------------------------------------


def test_follow_unfollow_and_notification_switches():
    c = _browser()
    csrf = _demo(c)
    org = uid("org", "ols")
    made = c.post(f"{V1}/me/follows", json={"target_type": "organisation", "target_id": org}, headers=csrf).json()

    listed = c.get(f"{V1}/me/follows").json()
    patched = c.patch(f"{V1}/me/follows/{made['id']}/notifications", json={"goal": False}, headers=csrf).json()

    assert made["target"]["name"] == "OLS" and made["target_type"] == "organisation"
    assert any(f["id"] == made["id"] for f in listed)
    assert patched["notify"]["goal"] is False and patched["notify"]["result"] is True
    assert c.delete(f"{V1}/me/follows/{made['id']}", headers=csrf).status_code == 204
    assert all(f["target_id"] != org for f in c.get(f"{V1}/me").json()["follows"])


def test_notifications_page_and_mark_read():
    c = _browser()
    csrf = _demo(c)
    page = c.get(f"{V1}/me/notifications", params={"limit": 3}).json()

    assert len(page["items"]) == 3 and page["next_cursor"] and page["unread_count"] >= 3
    more = c.get(f"{V1}/me/notifications", params={"limit": 3, "cursor": page["next_cursor"]}).json()
    assert not {n["id"] for n in more["items"]} & {n["id"] for n in page["items"]}
    assert c.post(f"{V1}/me/notifications/read", json={}, headers=csrf).status_code == 204
    assert c.get(f"{V1}/me/notifications").json()["unread_count"] == 0


# ---- scoring ---------------------------------------------------------------------------------


def test_a_scorer_pass_scores_a_match_from_kick_off():
    c = _browser()
    njc11 = store.get_match("njc11")  # kick-off now, so it is today's match whatever the time of day
    store.matches = [m.model_copy(update={"starts_at": store.now}) if m is njc11 else m for m in store.matches]
    passes = {p["tournament_id"]: p["token"] for p in c.get("/mock/scorer-passes").json()}
    auth = {"Authorization": f"Pass {passes[uid('tournament', 'njc-u17')]}"}
    mine = c.get(f"{V1}/scoring/me", headers=auth).json()
    match = next(m for m in mine if m["status"] == "scheduled")
    mid, home = match["match_id"], match["home"]["id"]

    assert c.post(f"{V1}/matches/{mid}/start", headers=auth).json()["status"] == "live"
    goal = c.post(f"{V1}/matches/{mid}/events", json={"client_seq": 2, "type": "goal", "team_id": home}, headers=auth)
    again = c.post(f"{V1}/matches/{mid}/events", json={"client_seq": 2, "type": "goal", "team_id": home}, headers=auth)
    state = c.get(f"{V1}/matches/{mid}/scoring", headers=auth).json()
    undo = c.post(f"{V1}/matches/{mid}/events/{goal.json()['seq']}/undo", json={"client_seq": 3}, headers=auth)

    assert goal.status_code == 201 and goal.json()["live"]["home_goals"] == 1
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert state["role"] == "scorer" and state["last_client_seq"] == 2 and state["events"][0]["type"] == "goal"
    assert undo.status_code == 201 and undo.json()["live"]["home_goals"] == 0
    finished = c.post(f"{V1}/matches/{mid}/finish", json={"home_goals": 0, "away_goals": 0}, headers=auth)
    assert finished.json()["status"] == "finished"
    late = c.post(f"{V1}/matches/{mid}/events", json={"client_seq": 9, "type": "goal", "team_id": home}, headers=auth)
    assert late.status_code == 409 and late.json()["code"] == "match_not_live"


def test_scoring_needs_a_pass_or_an_organiser():
    guest, fan, organiser = _browser(), _browser(), _browser()
    _demo(fan)
    _demo(organiser, "organiser")
    mid = uid("match", "njc11")

    assert guest.get(f"{V1}/matches/{mid}/scoring").status_code == 401
    assert fan.get(f"{V1}/matches/{mid}/scoring").json()["code"] == "scorer_not_assigned"
    assert organiser.get(f"{V1}/matches/{mid}/scoring").json()["role"] == "organiser"
    pad = organiser.get(f"{V1}/sports/football/event-types").json()
    assert {"goal", "penalty_goal", "yellow_card"} <= {b["id"] for b in pad["buttons"]}
    assert organiser.get(f"{V1}/sports/curling/event-types").status_code == 422


def test_the_match_socket_starts_with_a_snapshot():
    c = _browser()
    _demo(c)
    mid = uid("match", "njc5")
    token = c.get(f"{V1}/live/token", params={"match_id": mid}).json()["token"]

    with c.websocket_connect(f"{V1}/live/matches/{mid}?token={token}") as ws:
        first = ws.receive_json()
    with c.websocket_connect(f"{V1}/live/matches/{mid}?token=wrong") as ws:
        try:
            ws.receive_json()
            closed = None
        except Exception as exc:  # the server closes with 4401
            closed = getattr(exc, "code", None)

    assert first["type"] == "snapshot" and first["match_id"] == mid
    assert first["data"]["score"]["home_goals"] == 1 and isinstance(first["data"]["timeline"], list)
    assert closed == 4401
