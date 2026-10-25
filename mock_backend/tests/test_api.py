import os
import secrets

os.environ["OURSPORT_SIMULATE"] = "0"  # deterministic: no background ticker

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, store  # noqa: E402
from app.v1.ids import uid  # noqa: E402

client = TestClient(app)


def setup_function():
    store.reset()


def _demo(c: TestClient, plan: str = "premium") -> dict:
    """Sign this test browser in as one of the old demo personas (premium, free, scorer,
    publisher, editor) for the pages still on the old routes. Test-only: the app signs in
    with `POST /api/v1/auth/demo-login` (fan, organiser, editor)."""
    sid = c.cookies.get("lp_sid")
    session = store.session(sid) if sid else None
    if session is None:
        sid = secrets.token_urlsafe(8)
        session = store.new_session(sid)
        c.cookies.set("lp_sid", sid)
    session.sign_in_demo(plan)
    return session.me().model_dump(by_alias=True, mode="json")


def _session(c: TestClient):
    sid = c.cookies.get("lp_sid")
    session = store.session(sid) if sid else None
    if session is None:
        sid = secrets.token_urlsafe(8)
        session = store.new_session(sid)
        c.cookies.set("lp_sid", sid)
    return session


def _v1(c: TestClient) -> dict:
    """Give this browser v1 cookies for the same person (the fan pages use v1); returns the
    CSRF header for unsafe v1 requests."""
    from app.v1 import auth as A

    s = A.state(store)
    access, csrf = secrets.token_urlsafe(12), secrets.token_urlsafe(8)
    s.access[access] = A.Grant(_session(c), A._now() + A.ACCESS_TTL)
    c.cookies.set(A.ACCESS_COOKIE, access)
    c.cookies.set(A.CSRF_COOKIE, csrf)
    return {A.CSRF_HEADER: csrf}


def _member_account(c: TestClient, email: str) -> dict:
    """A newly signed-up member with this email (sign-up itself is v1's magic link now)."""
    from app import club_teams

    profile = _session(c)
    profile.signed_in, profile.email, profile.account_email = True, email.lower(), email.lower()
    profile.name = email.split("@")[0].title()
    club_teams.apply_family_links(store, profile)
    return profile.me().model_dump(by_alias=True, mode="json")


def _me(c: TestClient) -> dict:
    return _session(c).me().model_dump(by_alias=True, mode="json")


def test_tick_advances_live_clock_and_can_score():
    before = {m.id: m.clock for m in store.matches if m.status == "live"}
    store.rng.random = lambda: 0.0  # force a score
    store.tick()
    after = {m.id: m for m in store.matches if m.status == "live"}
    assert all(after[i].clock == c + 1 for i, c in before.items())
    assert sum(m.flash is not None for m in after.values()) == 1
    assert store.posts[0].type == "score"


def test_due_upcoming_game_goes_live():
    m4 = next(m for m in store.matches if m.id == "m4")
    m4.starts_at = 0
    store.tick()
    assert next(m for m in store.matches if m.id == "m4").status == "live"


# ---- Explore & search (F2) -------------------------------------------------

# ---- Club page (F3), me & follows ------------------------------------------

def _fresh_client():
    return TestClient(app)  # new cookie jar = new browser session


# ---- Events / tournaments (F5) ---------------------------------------------

# ---- Match page (F6) ---------------------------------------------------------

# ---- Story page (F7) ---------------------------------------------------------

# ---- Junior protection -------------------------------------------------------

# ---- Team page (F4) -------------------------------------------------------------

# ---- Player page (F8) -----------------------------------------------------------

# ---- Following (F9) ------------------------------------------------------------------

# ---- Account & subscription (F10) ------------------------------------------------------

def test_free_plan_and_invite_codes():
    c = _fresh_client()
    assert c.post("/api/me/redeem-code", json={"code": "OLS-FAMILY-2026"}).status_code == 401  # members only
    me = _demo(c, "free")
    assert me["premium"] is None and me["family"] == []
    bad = c.post("/api/me/redeem-code", json={"code": "NOPE-123"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_code"
    me = c.post("/api/me/redeem-code", json={"code": " ols-family-2026 "}).json()
    assert me["premium"]["viaClubId"] == "ols"
    _v1(c)
    assert c.get(f"/api/v1/live/token?match_id={uid('match', 'm1')}").status_code == 200  # members follow live


# ---- Notifications (F11) and news feed -----------------------------------------------

# ---- Sign up / log in / reset password (F12) ------------------------------------------

SIGNUP = {"email": "Aino.K@example.com", "password": "correct horse", "language": "fi", "acceptTerms": True}


# ---- Accept invite (F13) ----------------------------------------------------------------

def test_invite_states():
    v = client.get("/api/invites/ols-premium-2026").json()
    assert v["status"] == "valid" and v["club"]["name"] == "OLS" and v["offer"]["kind"] == "premium_seat"
    assert v["club"]["contactEmail"] == "info@ols.example.org" and v["invitedBy"].startswith("Mari")
    assert client.get("/api/invites/karpat-premium-expired").json()["status"] == "expired"
    assert client.get("/api/invites/hoops-premium-used").json()["status"] == "used"
    r = client.get("/api/invites/nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "invalid"


def test_accept_premium_seat():
    c = _fresh_client()
    assert c.post("/api/invites/ols-premium-2026/accept").status_code == 401  # log in first
    _member_account(c, "new.fan@example.com")
    r = c.post("/api/invites/ols-premium-2026/accept").json()
    assert r["me"]["premium"]["viaClubId"] == "ols" and "ols" in r["me"]["follows"]["clubs"]
    assert r["invite"]["status"] == "accepted_by_you"
    assert c.post("/api/invites/ols-premium-2026/accept").status_code == 200  # idempotent for the same member
    other = _fresh_client()
    assert other.get("/api/invites/ols-premium-2026").json()["status"] == "used"
    _demo(other, "free")
    used = other.post("/api/invites/ols-premium-2026/accept")
    assert used.status_code == 410 and used.json()["detail"]["code"] == "used"


def test_accept_role_and_expired():
    c = _fresh_client()
    _demo(c, "free")
    me = c.post("/api/invites/tarmo-scorer-2026/accept").json()["me"]
    assert me["roles"] == [{"clubId": "tarmo", "clubName": "Oulun Tarmo", "role": "scorer", "label": "Scorer"}]
    assert me["premium"] is None  # a role doesn't include Premium
    assert c.post("/api/invites/karpat-premium-expired/accept").json()["detail"]["code"] == "expired"


# ---- Club portal ---------------------------------------------------------------------------

def test_demo_premium_account_admins_two_clubs():
    c = _fresh_client()
    roles = _demo(c)["roles"]
    assert [(r["clubId"], r["role"]) for r in roles] == [("tarmo", "admin"), ("ols", "admin")]
    assert roles[0]["label"] == "Club admin"
    assert _demo(c, "free")["roles"] == [
        {"clubId": "tarmo", "clubName": "Oulun Tarmo", "role": "admin", "label": "Club admin"},
        {"clubId": "ols", "clubName": "OLS", "role": "admin", "label": "Club admin"},
    ]  # roles stay with the account
    assert _demo(_fresh_client(), "free")["roles"] == []


# ---- Club dashboard (C1) -----------------------------------------------------------------

def test_dashboard_is_for_club_admins():
    assert _fresh_client().get("/clubs/tarmo/dashboard").status_code == 401
    fan = _fresh_client()
    _demo(fan, "free")
    r = fan.get("/clubs/tarmo/dashboard")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_club_admin"
    admin = _fresh_client()
    _demo(admin)
    assert admin.get("/clubs/karpat/dashboard").status_code == 403  # admins Tarmo + OLS only
    assert admin.get("/clubs/nope/dashboard").status_code == 404


def test_dashboard_content():
    admin = _fresh_client()
    _demo(admin)
    d = admin.get("/clubs/tarmo/dashboard").json()
    k = d["kpis"]
    assert k["premiumSeatsTotal"] == 50 and k["premiumSeatsUsed"] >= 32  # base 31 + the demo admin (Premium via Tarmo)
    assert k["followers"] >= 1241 and k["openCorrections"] == 1 and k["matchesThisWeek"] >= 1
    nxt = d["nextMatches"]
    assert all(n["match"]["status"] == "upcoming" for n in nxt)
    assert {n["match"]["id"]: n["scorer"] for n in nxt}["m9"] == "Jari Niemi"
    pub = [s["publishedAt"] for s in d["stories"]]
    assert pub == sorted(pub, reverse=True) and len(pub) <= 5
    before = k["followers"]
    fan = _fresh_client()
    _member_account(fan, "f@example.com")
    _session(fan).clubs.append("tarmo")
    assert admin.get("/clubs/tarmo/dashboard").json()["kpis"]["followers"] == before + 1
    ols = admin.get("/clubs/ols/dashboard").json()
    assert {n["match"]["id"]: n["scorer"] for n in ols["nextMatches"]}.get("m8") is None  # -> "No scorer"


# ---- Club members and Premium seats (C2) ---------------------------------------------------

def _club_admin():
    c = _fresh_client()
    _demo(c)
    return c


def test_members_are_for_club_admins():
    assert _fresh_client().get("/clubs/tarmo/members").status_code == 401
    assert _club_admin().get("/clubs/karpat/members").status_code == 403
    page = _club_admin().get("/clubs/tarmo/members").json()
    seats = page["seats"]
    assert seats["total"] == 50 and seats["used"] == sum(
        1 for m in page["members"] if m["premium"] and m["status"] != "expired")
    assert {m["status"] for m in page["members"]} == {"invited", "active", "expired"}
    assert {m["role"] for m in page["members"]} == {"member", "scorer", "admin"}
    me = [m for m in page["members"] if m["isYou"]]
    assert len(me) == 1 and me[0]["role"] == "admin"


def test_bulk_invite_preview_and_errors():
    admin = _club_admin()
    taken = admin.get("/clubs/tarmo/members").json()["members"][1]["email"]
    rows = [
        {"email": "new.one@example.com", "name": "New One", "role": "scorer", "premium": True},
        {"email": "not-an-email", "role": "member"},
        {"email": taken.upper()},
        {"email": "new.one@example.com"},
        {"email": "x@example.com", "role": "boss"},
    ]
    r = admin.post("/clubs/tarmo/invites", json={"rows": rows, "dryRun": True})
    assert r.status_code == 200
    codes = [row["error"] and row["error"]["code"] for row in r.json()["rows"]]
    assert codes == [None, "email", "duplicate", "duplicate_in_list", "role"]
    assert r.json()["created"] == []
    r = admin.post("/clubs/tarmo/invites", json={"rows": rows})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_rows"
    assert len(r.json()["detail"]["rows"]) == 5
    assert not any(m["email"] == "new.one@example.com" for m in admin.get("/clubs/tarmo/members").json()["members"])


def test_bulk_invite_then_accept_link():
    admin = _club_admin()
    before = admin.get("/clubs/tarmo/members").json()["seats"]["used"]
    r = admin.post("/clubs/tarmo/invites", json={"rows": [
        {"email": "Scorer.Sam@example.com", "name": "Sam", "role": "scorer", "premium": True},
        {"email": "plain@example.com"},
    ]})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert [m["status"] for m in created] == ["invited", "invited"] and r.json()["seats"]["used"] == before + 1
    link = created[0]["inviteLink"]
    sam = _fresh_client()
    _member_account(sam, "scorer.sam@example.com")
    assert sam.get("/api" + link.replace("/invite/", "/invites/")).json()["offer"]["kind"] == "premium_seat"
    me = sam.post("/api" + link.replace("/invite/", "/invites/") + "/accept").json()["me"]
    assert me["premium"]["viaClubId"] == "tarmo" and {(x["clubId"], x["role"]) for x in me["roles"]} == {("tarmo", "scorer")}
    row = next(m for m in admin.get("/clubs/tarmo/members").json()["members"] if m["id"] == created[0]["id"])
    assert row["status"] == "active"
    # removing Premium / the member reaches the account
    admin.patch(f"/clubs/tarmo/members/{row['id']}", json={"premium": False})
    assert _me(sam)["premium"] is None
    assert admin.delete(f"/clubs/tarmo/members/{row['id']}").status_code == 200
    assert _me(sam)["roles"] == []


def test_seat_limit_and_self_protection():
    admin = _club_admin()
    plain = [{"email": f"plain{i}@example.org"} for i in range(60)]
    assert admin.post("/clubs/tarmo/invites", json={"rows": plain}).status_code == 200
    page = admin.get("/clubs/tarmo/members").json()
    free = page["seats"]["total"] - page["seats"]["used"]
    no_premium = [m for m in page["members"] if not m["premium"] and m["status"] != "expired" and not m["isYou"]]
    for m in no_premium[:free]:
        assert admin.patch(f"/clubs/tarmo/members/{m['id']}", json={"premium": True}).status_code == 200
    r = admin.patch(f"/clubs/tarmo/members/{no_premium[free]['id']}", json={"premium": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "seat_limit"
    r = admin.post("/clubs/tarmo/invites", json={"rows": [{"email": "late@example.com", "premium": True}]})
    assert r.status_code == 409 and r.json()["detail"]["rows"][0]["error"]["code"] == "seat_limit"
    me = next(m for m in page["members"] if m["isYou"])
    assert admin.delete(f"/clubs/tarmo/members/{me['id']}").json()["detail"]["code"] == "self"
    assert admin.patch(f"/clubs/tarmo/members/{me['id']}", json={"role": "member"}).status_code == 409


def test_resend_invite():
    admin = _club_admin()
    members = admin.get("/clubs/ols/members").json()["members"]
    expired = next(m for m in members if m["status"] == "expired")
    r = admin.post(f"/clubs/ols/members/{expired['id']}/resend").json()["member"]
    assert r["status"] == "invited" and r["invitedAt"] > expired["invitedAt"]
    active = next(m for m in members if m["status"] == "active")
    assert admin.post(f"/clubs/ols/members/{active['id']}/resend").json()["detail"]["code"] == "already_active"


# ---- Teams and players (C3) -----------------------------------------------------------------

def test_club_teams_list_and_create():
    admin = _club_admin()
    assert _fresh_client().get("/clubs/tarmo/teams").status_code == 401
    d = admin.get("/clubs/tarmo/teams").json()
    teams = {t["team"]["id"]: t for t in d["teams"]}
    assert set(teams) == {"tarmo", "tarmou17"}
    assert "Northern Junior Cup U17" in teams["tarmou17"]["competitions"] and teams["tarmou17"]["minors"] > 0
    r = admin.post("/clubs/tarmo/teams", json={"name": "Tarmo Women", "sport": "football", "ageGroup": "senior", "league": "Naisten Kakkonen"})
    assert r.status_code == 201 and r.json()["team"]["clubId"] == "tarmo"
    tid = r.json()["team"]["id"]
    assert admin.post("/clubs/tarmo/teams", json={"name": "tarmo women", "sport": "football", "ageGroup": "senior"}).status_code == 409
    assert admin.patch(f"/clubs/tarmo/teams/{tid}", json={"league": "Kolmonen"}).json()["league"] == "Kolmonen"
    fan_side = client.get(f"/api/v1/organisations/{uid('org', 'tarmo')}/teams").json()
    assert fan_side[-1]["id"] == uid("team", tid)  # the fan side sees the new team
    assert admin.patch(f"/clubs/ols/teams/{tid}", json={"league": "x"}).status_code == 404


def test_roster_and_junior_rules():
    admin = _club_admin()
    assert _club_admin().get("/teams/karpat/players").status_code == 403
    roster = admin.get("/teams/tarmou17/players").json()
    cutoff = roster["minorCutoffYear"]
    assert all(p["minor"] == (p["birthYear"] >= cutoff) for p in roster["players"])
    no_consent = next(p for p in roster["players"] if p["minor"] and not p["consent"])
    assert no_consent["visibility"] == "hidden" and no_consent["allowed"] == ["hidden"]
    # under-18 defaults to hidden; public / family without consent is refused
    r = admin.post("/teams/tarmou17/players", json={"name": "Junior Test", "number": 77, "birthYear": cutoff + 1})
    assert r.status_code == 201 and r.json()["visibility"] == "hidden"
    pid = r.json()["id"]
    for vis in ("public", "family"):
        r = admin.patch(f"/teams/tarmou17/players/{pid}", json={"visibility": vis})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"
    assert admin.post("/teams/tarmou17/players", json={"name": "X", "number": 1, "birthYear": 2000}).status_code in (409, 422)
    assert admin.post("/teams/tarmou17/players", json={"name": "Pub Kid", "number": 78, "birthYear": cutoff + 1,
                                                       "visibility": "public"}).status_code == 409
    # a minor can't consent for themselves; a guardian's family consent allows family only
    assert admin.post(f"/players/{pid}/consent", json={"givenBy": "Junior Test", "relation": "player",
                                                       "linkFamily": False}).status_code == 422
    p = admin.post(f"/players/{pid}/consent", json={"givenBy": "Parent Test", "email": "parent@example.com", "scope": "family"}).json()
    assert p["allowed"] == ["family", "hidden"] and p["family"][0]["email"] == "parent@example.com"
    assert admin.patch(f"/teams/tarmou17/players/{pid}", json={"visibility": "public"}).status_code == 409
    assert admin.patch(f"/teams/tarmou17/players/{pid}", json={"visibility": "family"}).json()["visibility"] == "family"
    # the linked parent signs up later and sees the profile; others don't
    parent = _fresh_client()
    _member_account(parent, "parent@example.com")
    _v1(parent)
    page = f"/api/v1/players/{uid('player', pid)}"
    assert parent.get(page).status_code == 200
    assert client.get(page).status_code == 404  # hidden players are not found (docs/09)
    # hidden: not even family
    admin.patch(f"/teams/tarmou17/players/{pid}", json={"visibility": "hidden"})
    assert parent.get(page).status_code == 404
    # public consent -> public allowed; withdrawing it falls back to hidden
    admin.post(f"/players/{pid}/consent", json={"givenBy": "Parent Test", "email": "parent@example.com", "scope": "public"})
    assert admin.patch(f"/teams/tarmou17/players/{pid}", json={"visibility": "public"}).json()["visibility"] == "public"
    assert client.get(page).status_code == 200
    assert admin.delete(f"/players/{pid}/consent").json()["visibility"] == "hidden"
    assert client.get(page).status_code == 404


def test_adult_players_and_family_links():
    admin = _club_admin()
    r = admin.post("/teams/tarmo/players", json={"name": "Adult Test", "number": 88, "birthYear": 1995, "position": "Forward"})
    assert r.status_code == 201 and r.json()["visibility"] == "public" and r.json()["allowed"] == ["public", "hidden"]
    pid = r.json()["id"]
    assert admin.post("/teams/tarmo/players", json={"name": "Dup", "number": 88, "birthYear": 1995}).json()["detail"]["code"] == "number_taken"
    # changing the birth year to an under-18 while public is refused
    assert admin.patch(f"/teams/tarmo/players/{pid}", json={"birthYear": 2015}).status_code == 409
    assert admin.post(f"/players/{pid}/family", json={"name": "Mum", "email": "mum@example.com"}).status_code == 409
    # family link on a junior, then unlink
    junior = next(p for p in admin.get("/teams/olsu17/players").json()["players"] if p["minor"])
    linked = admin.post(f"/players/{junior['id']}/family", json={"name": "Dad", "email": "dad@example.com"}).json()
    link = next(f for f in linked["family"] if f["email"] == "dad@example.com")
    assert link["hasAccount"] is False
    assert all(f["id"] != link["id"] for f in admin.delete(f"/players/{junior['id']}/family/{link['id']}").json()["family"])


# ---- Matches and scorers (C4) ---------------------------------------------------------------

def test_club_matches_list():
    assert _fresh_client().get("/clubs/tarmo/matches").status_code == 401
    d = _club_admin().get("/clubs/tarmo/matches").json()
    assert {s["name"] for s in d["scorers"]} == {"Jari Niemi", "Pekka Rautio"}
    up = {m["match"]["id"]: m for m in d["upcoming"]}
    assert up["m9"]["scorer"]["name"] == "Jari Niemi" and up["m9"]["dataLevel"] == "live"
    assert up["m11"]["status"] == "awaiting_result" and up["m11"]["canFinish"] is True
    assert up["m10"]["dataLevel"] == "results_only"
    assert up["m10"]["canFinish"] is False  # not started yet
    assert all(m["match"]["status"] == "finished" for m in d["past"])
    ends = [m["match"]["endedAt"] for m in d["past"]]
    assert ends == sorted(ends, reverse=True)


def test_assign_scorer_and_data_level():
    admin = _club_admin()
    pekka = next(s for s in admin.get("/clubs/tarmo/matches").json()["scorers"] if s["name"] == "Pekka Rautio")
    r = admin.patch("/matches/m9", json={"scorerId": pekka["id"]})
    assert r.status_code == 200 and r.json()["scorer"]["name"] == "Pekka Rautio"
    assert {n["match"]["id"]: n["scorer"] for n in admin.get("/clubs/tarmo/dashboard").json()["nextMatches"]}["m9"] == "Pekka Rautio"
    assert admin.patch("/matches/m9", json={"scorerId": None}).json()["scorer"] is None
    member = next(m for m in admin.get("/clubs/tarmo/members").json()["members"] if m["role"] == "member")
    assert admin.patch("/matches/m9", json={"scorerId": member["id"]}).json()["detail"]["code"] == "not_a_scorer"
    assert admin.patch("/matches/m9", json={"dataLevel": "results_only"}).json()["dataLevel"] == "results_only"
    assert admin.patch("/matches/m1", json={"dataLevel": "results_only"}).json()["detail"]["code"] == "started"  # live
    assert admin.patch("/matches/r4", json={"scorerId": None}).json()["detail"]["code"] == "finished"
    assert admin.patch("/matches/m2", json={"scorerId": None}).status_code == 403  # Kiekko-Oulu game
    fan = _fresh_client()
    _demo(fan, "free")
    assert fan.patch("/matches/m9", json={"scorerId": None}).status_code == 403


def test_enter_result():
    admin = _club_admin()
    assert admin.post("/matches/m10/finish", json={"score": [1, 0]}).json()["detail"]["code"] == "not_started"
    r = admin.post("/matches/m11/finish", json={"score": [2, 3]})
    assert r.status_code == 200 and r.json()["status"] == "finished"
    fan = client.get(f"/api/v1/matches/{uid('match', 'm11')}").json()
    assert fan["match"]["status"] == "finished"
    assert (fan["match"]["score"]["home_goals"], fan["match"]["score"]["away_goals"]) == (2, 3)
    report = client.get(f"/api/v1/stories/{uid('story', 'report-m11:en')}")
    assert report.status_code == 200  # the AI match report is written
    assert admin.post("/matches/m11/finish", json={"score": [2, 3]}).status_code == 200  # same result again: fine (retries)
    assert admin.post("/matches/m11/finish", json={"score": [4, 3]}).json()["detail"]["code"] == "finished"
    assert admin.post("/matches/m1/finish", json={"score": [3, 1]}).json()["match"]["score"] == [3, 1]  # end a live game
    assert admin.post("/matches/m9/finish", json={"score": [-1, 0]}).status_code in (409, 422)


# ---- Club profile and sponsors (C5) ---------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_club_profile_edit():
    admin = _club_admin()
    assert _fresh_client().get("/clubs/tarmo").status_code == 401
    d = admin.get("/clubs/tarmo").json()
    assert d["club"]["name"] == "Oulun Tarmo" and d["sportsInUse"] == ["football"]
    r = admin.patch("/clubs/tarmo", json={"description": "Football in Oulu since 1923.", "color": "#AA3300",
                                         "secondaryColor": "#ffffff", "city": "Oulu", "sports": ["football", "floorball"]})
    assert r.status_code == 200, r.text
    club = client.get(f"/api/v1/organisations/{uid('org', 'tarmo')}").json()  # the fan side sees it
    assert club["colors"]["primary"] == "#aa3300" and "floorball" in club["sports"]
    assert admin.patch("/clubs/tarmo", json={"sports": ["floorball"]}).json()["detail"]["code"] == "sport_in_use"
    assert admin.patch("/clubs/tarmo", json={"sports": ["curling"]}).status_code == 422
    assert admin.patch("/clubs/tarmo", json={"color": "red"}).status_code == 422
    assert admin.patch("/clubs/tarmo", json={"logoUrl": "https://evil.example/x.png"}).status_code == 422
    assert admin.patch("/clubs/karpat", json={"description": "x"}).status_code == 403


def test_uploads_and_sponsors():
    admin = _club_admin()
    assert _fresh_client().post("/uploads", content=PNG, headers={"content-type": "image/png"}).status_code == 401
    assert admin.post("/uploads", content=b"<svg/>", headers={"content-type": "image/svg+xml"}).status_code == 415
    assert admin.post("/uploads", content=b"not a png", headers={"content-type": "image/png"}).status_code == 415
    up = admin.post("/uploads", content=PNG, headers={"content-type": "image/png"}).json()
    img = client.get(up["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == PNG
    assert admin.patch("/clubs/tarmo", json={"logoUrl": up["url"]}).json()["club"]["logoUrl"] == up["url"]
    sp = admin.post("/clubs/tarmo/sponsors", json={"name": "Oulun Leipomo", "url": "leipomo.example.fi",
                                                  "logoUrl": up["url"], "showOn": ["reports"]})
    assert sp.status_code == 201 and sp.json()["url"] == "https://leipomo.example.fi"
    sid = sp.json()["id"]
    assert admin.post("/clubs/tarmo/sponsors", json={"name": "oulun leipomo"}).json()["detail"]["code"] == "sponsor_exists"
    org = f"/api/v1/organisations/{uid('org', 'tarmo')}"
    assert any(s["id"] == sid for s in client.get(org).json()["sponsors"])
    assert admin.patch(f"/clubs/tarmo/sponsors/{sid}", json={"showOn": ["club_page"]}).json()["showOn"] == ["club_page"]
    assert admin.delete(f"/clubs/tarmo/sponsors/{sid}").status_code == 204
    assert all(s["id"] != sid for s in client.get(org).json()["sponsors"])


# ---- Billing (C6) -------------------------------------------------------------------------------

def test_billing_summary_and_invoices():
    assert _fresh_client().get("/clubs/tarmo/billing").status_code == 401
    admin = _club_admin()
    b = admin.get("/clubs/tarmo/billing").json()
    assert b["plan"] == "Club" and b["seatsTotal"] == 50 and b["pricePerSeatCents"] == 300
    assert b["monthlyNetCents"] == 50 * 300 and b["minSeats"] == b["seatsUsed"]
    assert b["paymentMethod"]["last4"] == "4242" and "number" not in b["paymentMethod"]
    assert b["nextInvoiceDate"].endswith("-01") and len(b["invoices"]) == 6
    inv = b["invoices"][0]
    assert inv["totalCents"] == inv["netCents"] + inv["vatCents"]
    pdf = admin.get(inv["pdfUrl"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-")
    assert inv["number"].encode() in pdf.content
    assert _fresh_client().get(inv["pdfUrl"]).status_code == 401
    assert admin.get("/clubs/karpat/billing").status_code == 403


def test_change_seats():
    admin = _club_admin()
    b = admin.get("/clubs/tarmo/billing").json()
    prev = admin.post("/clubs/tarmo/billing/seats", json={"seats": 60, "preview": True}).json()
    assert prev["applied"] is False and prev["proratedNetCents"] > 0
    assert admin.get("/clubs/tarmo/billing").json()["seatsTotal"] == 50  # preview changes nothing
    r = admin.post("/clubs/tarmo/billing/seats", json={"seats": 60}).json()
    assert r["applied"] and r["billing"]["seatsTotal"] == 60 and r["billing"]["pendingChargeCents"] > 0
    assert admin.get("/clubs/tarmo/members").json()["seats"]["total"] == 60  # C2 sees the new seats
    low = admin.post("/clubs/tarmo/billing/seats", json={"seats": b["seatsUsed"] - 1})
    assert low.status_code == 409 and low.json()["detail"]["code"] == "seats_in_use"
    assert admin.post("/clubs/tarmo/billing/seats", json={"seats": 60}).json()["detail"]["code"] == "no_change"
    down = admin.post("/clubs/tarmo/billing/seats", json={"seats": b["seatsUsed"]}).json()
    assert down["proratedNetCents"] == 0 and down["billing"]["seatsTotal"] == b["seatsUsed"]


def test_billing_portal_is_hosted_by_the_provider():
    admin = _club_admin()
    s = admin.post("/clubs/tarmo/billing/portal", json={"returnPath": "https://evil.example/"}).json()
    assert s["url"].startswith("/billing-provider/session/")
    page = client.get(s["url"])
    assert page.status_code == 200 and "Oulun Tarmo" in page.text and "<input" not in page.text  # no card form of ours
    assert 'href="/club/tarmo/billing?portal=return"' in page.text  # unsafe return path replaced
    r = client.post(s["url"] + "/simulate-update", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/club/tarmo/billing?portal=updated"
    assert admin.get("/clubs/tarmo/billing").json()["paymentMethod"]["last4"] != "4242"
    assert client.get(s["url"]).status_code == 410  # single use


# ---- Corrections (C7) ------------------------------------------------------------------------------

def test_corrections_list():
    assert _fresh_client().get("/corrections", params={"club": "tarmo"}).status_code == 401
    admin = _club_admin()
    assert admin.get("/corrections", params={"club": "karpat"}).status_code == 403
    d = admin.get("/corrections", params={"club": "tarmo"}).json()
    assert d["counts"] == {"open": 1, "fixed": 1, "rejected": 1}
    fan = next(i for i in d["items"] if i["source"] == "fan")
    assert fan["reporter"] is None and fan["match"]["id"] == "r4" and fan["storyTitle"]
    fixed = next(i for i in d["items"] if i["status"] == "fixed")
    assert fixed["resolution"] and fixed["reporter"].endswith("Oulun Tarmo")
    created = [i["createdAt"] for i in d["items"]]
    assert created == sorted(created, reverse=True)
    assert admin.get("/clubs/tarmo/dashboard").json()["kpis"]["openCorrections"] == 1


def test_report_and_resolve_correction():
    from app import corrections
    admin = _club_admin()
    body = {"clubId": "tarmo", "matchId": "r5", "field": "score", "message": "The final score is wrong.", "correctValue": "3–1"}
    r = admin.post("/corrections", json=body)
    assert r.status_code == 201 and r.json()["status"] == "open" and r.json()["source"] == "club"
    assert admin.post("/corrections", json=body).json()["detail"]["code"] == "duplicate"
    assert admin.post("/corrections", json={**body, "matchId": "m2"}).status_code == 422  # not Tarmo's match
    assert admin.post("/corrections", json={**body, "field": "weather"}).status_code == 422
    assert admin.post("/corrections", json={**body, "clubId": "karpat"}).status_code == 403
    assert admin.get("/clubs/tarmo/dashboard").json()["kpis"]["openCorrections"] == 2
    # a fan's story report reaches the club too
    fan = _fresh_client()
    _demo(fan, "free")
    report = f"/api/v1/stories/{uid('story', 'report-r5:en')}/corrections"
    assert fan.post(report, json={"text": "Wrong scorer in the second paragraph."}, headers=_v1(fan)).status_code == 201
    assert admin.get("/corrections", params={"club": "tarmo"}).json()["counts"]["open"] == 3
    # clubs can't resolve; editors (E3) can, and a fixed match correction is shown to fans
    assert admin.patch(f"/corrections/{r.json()['id']}", json={"status": "fixed"}).status_code == 403
    corrections.resolve(store, r.json()["id"], "fixed", "Score corrected.")
    assert store.get_match("r5").correction.message.startswith("Corrected: Score")
    assert admin.get("/clubs/tarmo/dashboard").json()["kpis"]["openCorrections"] == 2


# ---- Scorer: my matches (S1) -------------------------------------------------------------------

# ---- Scorer console (S2) -------------------------------------------------------------------------

def _scorer():
    c = _fresh_client()
    _demo(c, "scorer")
    return c


# ---- Publisher dashboard (P1) ----------------------------------------------------------------------

def _publisher():
    c = _fresh_client()
    _demo(c, "publisher")
    return c


def test_publisher_events():
    assert _fresh_client().get("/publisher/events").status_code == 401
    assert _club_admin().get("/publisher/events").json()["detail"]["code"] == "not_publisher"
    pub = _publisher()
    me = _me(pub)
    assert me["name"] == "Kaisa Ranta" and [r["role"] for r in me["roles"]] == ["publisher"]
    d = pub.get("/publisher/events").json()
    assert d["organisation"] == "Oulu Sport Events"
    st = {e["id"]: e["status"] for e in d["events"]}
    assert st == {"njc-u17": "live", "oulu-sixes": "live", "winter-futsal-26": "draft", "finbangla-26": "rules_pending",
                  "autumn-floorball-26": "finished"}
    assert [e["status"] for e in d["events"]][:2] == ["live", "live"]  # live first
    njc = next(e for e in d["events"] if e["id"] == "njc-u17")
    assert njc["tournamentId"] == "njc-u17" and njc["matchesTotal"] > njc["matchesPlayed"] > 0 and njc["reviewEnabled"]


def test_review_queue_mine():
    pub = _publisher()
    q = pub.get("/review-queue", params={"scope": "mine"}).json()
    assert q["reviewEnabledEvents"] == ["njc-u17", "finbangla-26"]  # FinBangla: review on, nothing waiting yet
    assert [i["eventId"] for i in q["items"]] == ["njc-u17", "njc-u17"]  # Sixes review is off: editors only
    assert q["items"][0]["createdAt"] <= q["items"][1]["createdAt"] and q["items"][0]["story"]["authorType"] == "ai"
    assert pub.get("/review-queue", params={"scope": "all"}).json()["detail"]["code"] == "not_editor"
    assert client.get(f"/api/v1/stories/{uid('story', 'draft-njc-day2:en')}").status_code == 404  # drafts aren't published
    assert _club_admin().get("/review-queue").status_code == 403


# ---- Create event wizard (P2) --------------------------------------------------------------------

def _future(days):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days)).isoformat()


def _basics(**kw):
    return {"name": "Oulu Spring Cup", "sport": "football", "startDate": _future(10), "endDate": _future(11),
            "venues": ["Raatti Stadium", "Heinäpää artificial turf"], "ageGroup": "u17", "languages": ["fi", "en"], **kw}


def test_wizard_basics_and_teams():
    pub = _publisher()
    assert _club_admin().post("/tournaments", json=_basics()).status_code == 403
    assert pub.post("/tournaments", json=_basics(endDate=_future(5))).json()["detail"]["field"] == "endDate"
    assert pub.post("/tournaments", json=_basics(sport="curling")).status_code == 422
    r = pub.post("/tournaments", json=_basics())
    assert r.status_code == 201 and r.json()["status"] == "draft" and r.json()["step"] == 1
    eid = r.json()["id"]
    assert any(e["id"] == eid and e["status"] == "draft" for e in pub.get("/publisher/events").json()["events"])
    assert _publisher().get(f"/tournaments/{eid}").status_code == 200  # same account, another browser
    # teams: existing (same sport only) and new
    assert pub.post(f"/tournaments/{eid}/teams", json={"teamId": "kko"}).json()["detail"]["code"] == "sport"
    for t in ("olsu17", "tarmou17", "kemiu17"):
        pub.post(f"/tournaments/{eid}/teams", json={"teamId": t})
    s = pub.post(f"/tournaments/{eid}/teams", json={"name": "Oulu Juniors", "short": "OJU"}).json()
    assert len(s["teams"]) == 4 and s["teams"][-1]["new"] and all(t["group"] == "A" for t in s["teams"])
    assert pub.post(f"/tournaments/{eid}/teams", json={"teamId": "olsu17"}).json()["detail"]["code"] == "team_added"
    # two groups: everyone must be placed, each group 2+
    s = pub.patch(f"/tournaments/{eid}", json={"groups": [{"id": "A", "name": "Group A"}, {"id": "B", "name": "Group B"}]}).json()
    assert pub.patch(f"/tournaments/{eid}", json={"step": 2}).json()["detail"]["code"] == "teams"
    ids = [t["id"] for t in s["teams"]]
    s = pub.patch(f"/tournaments/{eid}", json={"teamGroups": {ids[0]: "A", ids[1]: "A", ids[2]: "B", ids[3]: "B"}, "step": 2}).json()
    assert s["step"] == 2


def test_wizard_fixtures_and_rulebook():
    import time
    pub = _publisher()
    eid = pub.post("/tournaments", json=_basics()).json()["id"]
    for t in ("olsu17", "tarmou17", "kemiu17", "acou17"):
        pub.post(f"/tournaments/{eid}/teams", json={"teamId": t})
    assert pub.patch(f"/tournaments/{eid}", json={"step": 3}).json()["detail"]["code"] == "fixtures"
    rr = pub.post(f"/tournaments/{eid}/import", json={"kind": "round_robin", "dryRun": True}).json()
    assert len(rr["fixtures"]) == 6 and rr["problems"] == []
    bad = ("date,time,home,away,venue,group\n"
           f"{_future(10)},10:00,OLS U17,Tarmo U17,Raatti Stadium,A\n"
           f"{_future(30)},10:00,OLS U17,Nobody FC,Raatti Stadium,A\n"
           f"{_future(10)},25:00,Kemi City U17,Kemi City U17,Moon,A\n")
    r = pub.post(f"/tournaments/{eid}/import", json={"kind": "csv", "csv": bad})
    assert r.status_code == 422
    probs = r.json()["detail"]["problems"]
    assert {p["row"] for p in probs} == {2, 3} and any(p["field"] == "away" for p in probs if p["row"] == 2)
    good = ("date;time;home;away;venue;group\n"
            f"{'.'.join(reversed(_future(10).split('-')))};10.00;OLS U17;Tarmo U17;Raatti Stadium;A\n"
            f"{_future(10)};11:30;Kemi City U17;AC Oulu U17;Heinäpää artificial turf;A\n")
    s = pub.post(f"/tournaments/{eid}/import", json={"kind": "csv", "csv": good}).json()["setup"]
    assert len(s["fixtures"]) == 2 and s["fixtures"][0]["date"] == _future(10) and s["fixtures"][0]["time"] == "10:00"
    edited = [{**s["fixtures"][0], "time": "9:99"}, s["fixtures"][1]]
    assert pub.patch(f"/tournaments/{eid}", json={"fixtures": edited}).json()["detail"]["problems"][0]["field"] == "time"
    assert pub.patch(f"/tournaments/{eid}", json={"step": 3}).json()["step"] == 3
    # rulebook as pasted text -> reading -> done with rules
    assert pub.post(f"/tournaments/{eid}/rulebook", json={"text": "short"}).status_code == 422
    text = "Matches last 2 x 30 minutes. A win gives 3 points and a draw 1 point. Ties: goal difference, then head-to-head. Top 2 go through."
    r = pub.post(f"/tournaments/{eid}/rulebook", json={"text": text})
    assert r.status_code == 202 and r.json()["rulesJob"]["status"] == "reading"
    st = pub.get(f"/tournaments/{eid}/rules/status").json()
    assert st["status"] == "reading" and 0 <= st["progress"] < 100
    from app import event_setup
    store.publisher_events[eid]["rules_job"]["started_at"] -= (event_setup.READ_SECONDS + 1) * 1000  # fast-forward the mock AI
    st = pub.get(f"/tournaments/{eid}/rules/status").json()
    assert st["status"] == "done" and st["rules"]["pointsWin"] == 3
    rules = st["rules"]
    assert rules["matchMinutes"] == 60 and rules["tiebreakers"][:2] == ["Goal difference", "Head-to-head"] and rules["qualifyCount"] == 2
    assert next(e for e in pub.get("/publisher/events").json()["events"] if e["id"] == eid)["status"] == "rules_pending"
    # a file: PDF made by the invoice generator reads back as text
    from app.billing import _pdf
    pdf = _pdf([(11, "A win is worth 2 points. Net run rate decides ties.")])
    eid2 = pub.post("/tournaments", json=_basics(name="Cricket Day", sport="cricket")).json()["id"]
    pub.post(f"/tournaments/{eid2}/teams", json={"name": "Team One"}); pub.post(f"/tournaments/{eid2}/teams", json={"name": "Team Two"})
    pub.post(f"/tournaments/{eid2}/import", json={"kind": "round_robin"})
    r = pub.post(f"/tournaments/{eid2}/rulebook", content=pdf, headers={"content-type": "application/pdf", "x-filename": "rules.pdf"})
    assert r.status_code == 202 and r.json()["rulebook"]["name"] == "rules.pdf"
    assert "Net run rate" in event_setup.extract_rules("cricket", event_setup._pdf_text(pdf), 2, 1)["tiebreakers"]
    assert pub.post(f"/tournaments/{eid2}/rulebook", content=b"MZ...", headers={"content-type": "application/octet-stream"}).status_code == 415


# ---- Rules review (P3) ----------------------------------------------------------------------------

def test_rules_review_flow():
    pub = _publisher()
    assert _club_admin().get("/tournaments/finbangla-26/rules/summary").status_code == 403
    s = pub.get("/tournaments/finbangla-26/rules/summary").json()
    assert s["state"] == "draft" and not s["canConfirm"]
    cards = {c["id"]: c for c in s["cards"]}
    assert set(cards) == {"format", "points", "tiebreakers", "advancement", "match", "walkover"}
    q = cards["advancement"]["quote"]
    assert "top 2" in q["text"].lower() and q["text"][q["start"]:q["end"]].lower().startswith("top")
    assert {f["type"] for c in s["cards"] for f in c["fields"]} <= {"number", "select", "order"}  # no free text
    qs = {x["id"]: x for x in s["questions"]}
    assert {"three_way", "walkover"} <= set(qs)
    assert pub.post("/tournaments/finbangla-26/rules/confirm").json()["detail"]["code"] == "not_ready"
    # answer the questions, fix the failing test (no final decider), mark the examples
    s = pub.patch("/tournaments/finbangla-26/rules/draft", json={"answers": {"three_way": "mini_league", "walkover": qs["walkover"]["options"][0]["id"]},
                                                                "values": {"tiebreakers": ["net_run_rate", "head_to_head", "lots"]}}).json()
    assert not [t for t in s["tests"] if t["result"] == "fail"], s["tests"]
    assert 3 <= len(s["examples"]) <= 6 and all(x["mark"]["status"] == "pending" for x in s["examples"])
    three = next(x for x in s["examples"] if x["id"] == "three-level")
    assert "ranks them" in three["text"] and len(three["table"]) == 4
    bad = pub.patch("/tournaments/finbangla-26/rules/draft", json={"marks": {three["id"]: {"status": "incorrect"}}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "note"
    s = pub.patch("/tournaments/finbangla-26/rules/draft", json={"marks": {three["id"]: {"status": "incorrect", "note": "C should be first"}}}).json()
    assert not s["canConfirm"] and any("not correct" in b for b in s["blockers"])
    s = pub.patch("/tournaments/finbangla-26/rules/draft", json={"marks": {x["id"]: {"status": "correct"} for x in s["examples"]}}).json()
    assert s["canConfirm"], s["blockers"]
    # changing a rule changes some examples: their marks reset
    s2 = pub.patch("/tournaments/finbangla-26/rules/draft", json={"values": {"points.win": 3}}).json()
    assert not s2["canConfirm"] and any(x["mark"]["status"] == "pending" for x in s2["examples"])
    assert pub.patch("/tournaments/finbangla-26/rules/draft", json={"values": {"points.win": 99}}).status_code == 422
    assert pub.patch("/tournaments/finbangla-26/rules/draft", json={"values": {"format.knockout": "anything"}}).status_code == 422
    s = pub.patch("/tournaments/finbangla-26/rules/draft", json={"marks": {x["id"]: {"status": "correct"} for x in s2["examples"]}}).json()
    r = pub.post("/tournaments/finbangla-26/rules/confirm")
    assert r.status_code == 200 and r.json()["version"]["version"] == 1 and r.json()["summary"]["state"] == "confirmed"
    assert next(e for e in pub.get("/publisher/events").json()["events"] if e["id"] == "finbangla-26")["status"] == "scheduled"
    assert pub.post("/tournaments/finbangla-26/rules/confirm").status_code == 409  # nothing changed


def test_rules_engine_ranks_three_way_ties():
    from app.rules_review import _example_sets, rank
    rules = {"points": {"win": 3, "draw": 1, "loss": 0}, "walkover": {"for": 3, "against": 0}, "three_way": "mini_league",
             "tiebreakers": ["head_to_head", "goal_difference", "lots"]}
    three = next(x for x in _example_sets("football") if x["id"] == "three-level")
    assert rank(list("ABCD"), three["matches"], rules)[0][:3] == ["B", "A", "C"]  # mini-league
    rules["three_way"] = "overall"
    assert rank(list("ABCD"), three["matches"], rules)[0][:3] == ["A", "B", "C"]  # overall goal difference
    rules["tiebreakers"] = ["goal_difference", "lots"]
    two = next(x for x in _example_sets("football") if x["id"] == "two-level")
    assert rank(list("ABCD"), two["matches"], rules)[0][:2] == ["B", "A"]
    rules["tiebreakers"] = ["head_to_head", "lots"]
    assert rank(list("ABCD"), two["matches"], rules)[0][:2] == ["A", "B"]


def test_rules_failed_then_manual():
    pub = _publisher()
    eid = pub.post("/tournaments", json=_basics(name="Scan Cup")).json()["id"]
    for t in ("olsu17", "tarmou17"):
        pub.post(f"/tournaments/{eid}/teams", json={"teamId": t})
    pub.post(f"/tournaments/{eid}/import", json={"kind": "round_robin"})
    blank = b"%PDF-1.4\n%%EOF\n"  # a scan: no text inside
    pub.post(f"/tournaments/{eid}/rulebook", content=blank, headers={"content-type": "application/pdf", "x-filename": "scan.pdf"})
    store.publisher_events[eid]["rules_job"]["started_at"] -= 60_000
    assert pub.get(f"/tournaments/{eid}/rules/summary").json()["state"] == "failed"
    assert pub.post(f"/tournaments/{eid}/rules/retry").status_code == 202
    s = pub.patch(f"/tournaments/{eid}/rules/draft", json={"manual": True}).json()
    assert s["state"] == "draft" and s["cards"] and all(f["value"] in (None, [], 0) for c in s["cards"] for f in c["fields"] if c["id"] == "points")
    assert s["examples"] == [] and not s["canConfirm"]


# ---- E1 editor review queue ---------------------------------------------------------------

def _editor():
    c = _fresh_client()
    _demo(c, "editor")
    return c


def test_editor_queue_access_and_order():
    assert _fresh_client().get("/review-queue", params={"scope": "all"}).status_code == 401
    assert _publisher().get("/review-queue", params={"scope": "all"}).json()["detail"]["code"] == "not_editor"
    ed = _editor()
    me = _me(ed)
    assert any(r["role"] == "editor" for r in me["roles"])
    q = ed.get("/review-queue").json()
    assert q["scope"] == "all" and q["total"] == len(q["items"]) == q["counts"]["all"]
    prios = [i["priority"] for i in q["items"]]
    assert prios == sorted(prios, key=lambda p: p != "high")  # high first
    highs = [i["createdAt"] for i in q["items"] if i["priority"] == "high"]
    assert highs == sorted(highs)  # then the longest-waiting
    kinds = {i["kind"] for i in q["items"]}
    assert {"ai_story", "manual_news", "correction"} <= kinds
    assert {o["id"] for o in q["filters"]["reasons"]} == {"sensitive_topic", "blocked_claim", "junior_mention", "manual_news", "correction"}
    assert any(i["assignedTo"] == "Sanna Virta" for i in q["items"])


def test_editor_queue_filters_and_cursor():
    ed = _editor()
    full = ed.get("/review-queue").json()
    j = ed.get("/review-queue", params={"reason": "junior_mention"}).json()
    assert j["items"] and all(i["reason"] == "junior_mention" for i in j["items"])
    assert all(i["sport"] == "basketball" for i in ed.get("/review-queue", params={"sport": "basketball"}).json()["items"])
    assert all(i["language"] == "bn" for i in ed.get("/review-queue", params={"language": "bn"}).json()["items"])
    old = ed.get("/review-queue", params={"age": "over_120"}).json()
    assert old["total"] == full["counts"]["over_120"] > 0
    p1 = ed.get("/review-queue", params={"limit": 3}).json()
    assert len(p1["items"]) == 3 and p1["nextCursor"] == "3"
    p2 = ed.get("/review-queue", params={"limit": 3, "cursor": p1["nextCursor"]}).json()
    assert [i["id"] for i in p1["items"] + p2["items"]] == [i["id"] for i in full["items"][:6]]
    assert ed.get("/review-queue", params={"reason": "nope"}).status_code == 422


def test_editor_claim_and_take_next():
    ed = _editor()
    q = ed.get("/review-queue").json()
    first_free = next(i for i in q["items"] if not i["assignedTo"])
    assert first_free["priority"] == "high"
    got = ed.post("/review-queue/next/claim").json()
    assert got["id"] == first_free["id"] and got["assignedToMe"] and got["status"] == "in_review"
    assert ed.get("/review-queue", params={"assigned": "me"}).json()["total"] == 1
    taken = next(i for i in q["items"] if i["assignedTo"] == "Sanna Virta")
    r = ed.post(f"/review-queue/{taken['id']}/claim")
    assert r.status_code == 409 and r.json()["detail"]["by"] == "Sanna Virta"
    assert ed.post(f"/review-queue/{taken['id']}/claim", params={"force": True}).json()["assignedToMe"]
    corr = next(i for i in q["items"] if i["kind"] == "correction")
    assert ed.post(f"/review-queue/{corr['id']}/claim").json()["assignedToMe"]
    assert ed.post("/review-queue/rv-404/claim").status_code == 404
    for _ in range(q["counts"]["all"]):
        ed.post("/review-queue/next/claim")
    assert ed.post("/review-queue/next/claim").json()["detail"]["code"] == "empty"
    assert _publisher().post("/review-queue/next/claim").status_code == 403


# ---- E2 review item -------------------------------------------------------------------------

def _flags(d):
    a = d["annotated"]
    return [f for s in [a["title"], *a["summary"], *(x for p in a["body"] for x in p)] for f in s["flags"]]


def test_review_item_detail_checker_marks():
    ed = _editor()
    assert _publisher().get("/review-queue/rv-8").status_code == 403
    assert ed.get("/review-queue/rv-404").status_code == 404
    d = ed.get("/review-queue/rv-8").json()
    assert d["check"]["status"] == "flagged" and d["kind"] == "ai_story"
    reasons = {f["reason"] for f in _flags(d)}
    assert "Number not in the fact sheet: 10" in reasons and any("incident" in r for r in reasons)
    first = d["annotated"]["body"][0][0]
    assert first["text"].startswith("Oulu Hoops won 78–71") and "F3" in first["factIds"] and not first["flags"]
    score = next(f for f in d["facts"] if f["id"] == "F3")
    assert score["claim"] == "Final score" and "71–78" in score["value"]
    assert d["match"]["id"] == "r2" and d["history"][0]["action"] == "generated"
    assert d["nav"]["position"] == 1 and d["nav"]["nextId"]
    j = ed.get("/review-queue/rv-4").json()
    assert {f["reason"] for f in _flags(j)} == {"Names a junior player (Aaro Hämäläinen)", "Gives a young player’s age"}
    assert ed.get("/review-queue/rv-1").json()["ruleVersion"]["version"] == 2
    assert ed.get("/review-queue/rv-6").json()["check"]["status"] == "passed"
    rv5 = ed.get("/review-queue/rv-5").json()
    assert [h["action"] for h in rv5["history"]][:3] == ["generated", "sent_back", "regenerated"]


def test_review_item_edit_check_approve():
    ed = _editor()
    d = ed.get("/review-queue/rv-8").json()
    r = ed.post("/stories/draft-r2-report/approve", json={"itemId": "rv-8"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "red_flags"
    clean = {"itemId": "rv-8", "version": d["version"], "title": d["text"]["title"],
             "summary": "Oulu Hoops beat Raahe Rays away.", "body": ["Oulu Hoops won 78–71 away at Raahe Areena.", "Hoops pulled away late."]}
    e = ed.patch("/stories/draft-r2-report", json=clean).json()
    assert e["check"]["status"] == "stale" and e["version"] == d["version"] + 1 and e["assignedToMe"]
    assert ed.post("/stories/draft-r2-report/approve", json={}).json()["detail"]["code"] == "check_stale"
    stale = ed.patch("/stories/draft-r2-report", json={**clean, "title": "x"})
    assert stale.json()["detail"]["code"] == "stale_version"
    c = ed.post("/stories/draft-r2-report/check").json()
    assert c["check"]["status"] == "passed" and c["history"][-1]["action"] == "checked"
    a = ed.post("/stories/draft-r2-report/approve", json={}).json()
    assert a["decision"]["action"] == "approved" and a["nextId"] != "rv-8"
    assert store.get_story("draft-r2-report").summary == "Oulu Hoops beat Raahe Rays away."
    assert "rv-8" not in [i["id"] for i in ed.get("/review-queue").json()["items"]]
    assert ed.post("/stories/draft-r2-report/approve", json={"itemId": "rv-8"}).json()["detail"]["code"] == "decided"


def test_review_item_override_reject_regenerate_claims():
    from app.main import store

    ed = _editor()
    assert ed.post("/stories/draft-r1-report/approve", json={"verified": True, "note": "short"}).json()["detail"]["code"] == "red_flags"
    ok = ed.post("/stories/draft-r1-report/approve", json={"verified": True, "note": "Guardian consent on file, checked with club"}).json()
    assert ok["decision"]["flagsOverridden"] == 2 and store.editor_log[-1]["note"].startswith("Guardian")
    # someone else's item
    assert ed.post("/stories/draft-njc-day2/reject", json={"reason": "Not needed"}).json()["detail"]["code"] == "claimed"
    assert ed.post("/stories/draft-m7-preview/reject", json={"reason": "no"}).status_code == 422
    rj = ed.post("/stories/draft-m7-preview/reject", json={"reason": "Speculation about injuries"}).json()
    assert rj["decision"]["action"] == "rejected" and "draft-m7-preview" not in store.drafts
    # send back: gone from the queue, back a few seconds later without the flagged sentence
    rg = ed.post("/stories/draft-sixes-final/regenerate", json={"note": "Drop the unbeaten claim"}).json()
    assert "rv-3" not in [i["id"] for i in ed.get("/review-queue").json()["items"]]
    assert ed.get("/review-queue/rv-3").json()["status"] == "regenerating"
    assert rg["readyAt"] > store.now
    rec = next(r for r in store.review_items if r["id"] == "rv-3")
    rec["regenerate_at"] = store.now
    d = ed.get("/review-queue/rv-3").json()
    assert d["status"] == "pending" and d["version"] == 2 and d["check"]["status"] == "passed"
    assert all("unbeaten" not in p for p in d["text"]["body"]) and d["history"][-1]["action"] == "regenerated"
    # a correction: fix the number, approve -> story updated, report fixed
    corr = next(i for i in ed.get("/review-queue").json()["items"] if i["kind"] == "correction" and "4–1" in i["reasonText"])
    cd = ed.get(f"/review-queue/{corr['id']}").json()
    assert cd["correction"]["message"].startswith("OLS U17 won 4–1") and cd["check"]["status"] == "flagged"
    body = [p.replace("4–0", "4–1") for p in cd["text"]["body"]]
    ed.patch(f"/stories/{cd['storyId']}", json={"itemId": corr["id"], "title": cd["text"]["title"], "summary": cd["text"]["summary"], "body": body})
    assert ed.post(f"/stories/{cd['storyId']}/check", json={"itemId": corr["id"]}).json()["check"]["status"] == "passed"
    ed.post(f"/stories/{cd['storyId']}/approve", json={"itemId": corr["id"]})
    assert "4–1" in store.get_story(cd["storyId"]).body[0]
    assert next(r for r in store.error_reports if f"corr-{r['id']}" == corr["id"])["status"] == "fixed"


# ---- E3 published content and corrections ---------------------------------------------------

def test_published_list_filters():
    ed = _editor()
    assert _publisher().get("/stories").status_code == 403
    p = ed.get("/stories").json()
    assert p["total"] == p["counts"]["published"] > 10 and p["counts"]["reported"] == 2
    times = [i["publishedAt"] for i in p["items"]]
    assert times == sorted(times, reverse=True)
    s4 = next(i for i in ed.get("/stories", params={"q": "quarter-finals"}).json()["items"] if i["id"] == "s4")
    assert s4["openCorrections"] == 1 and s4["correctItemId"].startswith("corr-")
    ai = ed.get("/stories", params={"author": "ai", "limit": 100}).json()["items"]
    assert ai and all(i["authorType"] == "ai" for i in ai)
    manual = ed.get("/stories", params={"author": "manual", "limit": 100}).json()["items"]
    assert manual and all(i["authorType"] == "editor" for i in manual)
    rep = ed.get("/stories", params={"corrected": "reported"}).json()
    assert rep["total"] == 2
    ev = p["events"][0]["id"]
    assert all(i["eventId"] == ev for i in ed.get("/stories", params={"event": ev, "limit": 100}).json()["items"])
    day = ed.get("/stories", params={"date": "24h", "limit": 100}).json()["items"]
    assert len(day) <= p["total"]


def test_editor_corrections_resolve_and_unpublish():
    ed = _editor()
    c = ed.get("/corrections").json()
    assert c["counts"]["open"] == 2 and all(i["status"] == "open" for i in c["items"])
    assert {i["itemId"] for i in c["items"]} == {f"corr-{i['id']}" for i in c["items"]}
    first = c["items"][0]
    assert ed.patch(f"/corrections/{first['id']}", json={"status": "rejected", "note": "no"}).status_code == 422
    r = ed.patch(f"/corrections/{first['id']}", json={"status": "rejected", "note": "The video shows #10 scoring."}).json()
    assert r["status"] == "rejected"
    assert ed.patch(f"/corrections/{first['id']}", json={"status": "fixed"}).json()["detail"]["code"] == "resolved"
    assert first["itemId"] not in [i["id"] for i in ed.get("/review-queue").json()["items"]]
    assert ed.get("/corrections", params={"status": "rejected"}).json()["items"][0]["id"] == first["id"]
    # unpublish
    assert ed.post("/stories/s4/unpublish", json={"reason": "x"}).status_code == 422
    u = ed.post("/stories/s4/unpublish", json={"reason": "Wrong score, rewriting it"}).json()
    assert u["status"] == "unpublished" and u["unpublishedBy"] == "Antti Leinonen"
    assert ed.get(f"/api/v1/stories/{uid('story', 's4:en')}").status_code == 404
    assert ed.post("/stories/s4/unpublish", json={"reason": "again again"}).json()["detail"]["code"] == "unpublished"
    assert ed.get("/stories", params={"status": "unpublished"}).json()["items"][0]["id"] == "s4"
    assert _club_admin().post("/stories/r1-report/unpublish", json={"reason": "not mine"}).status_code == 403


def test_correct_live_story_shows_corrected_note():
    ed = _editor()
    row = next(i for i in ed.get("/stories", params={"corrected": "no", "author": "ai"}).json()["items"] if not i["openCorrections"])
    assert row["correctItemId"] == f"fix-{row['id']}"
    d = ed.get(f"/review-queue/{row['correctItemId']}").json()
    assert d["kind"] == "fix" and d["item"] is None and d["text"]["title"] == row["title"]
    body = d["text"]["body"] + ["Added line."]
    ed.patch(f"/stories/{row['id']}", json={"itemId": d["id"], "version": d["version"], "title": d["text"]["title"],
                                            "summary": d["text"]["summary"], "body": body})
    chk = ed.post(f"/stories/{row['id']}/check", json={"itemId": d["id"]}).json()["check"]
    payload = {"itemId": d["id"], "verified": bool(chk["flags"]), "note": "Checked against the scoresheet" if chk["flags"] else None}
    assert ed.post(f"/stories/{row['id']}/approve", json=payload).json()["detail"]["code"] == "public_note"
    ok = ed.post(f"/stories/{row['id']}/approve", json={**payload, "publicNote": "Added the closing line."}).json()
    assert ok["decision"]["action"] == "approved"
    st = store.get_story(row["id"])
    assert st.corrected_at and st.correction_note == "Added the closing line." and st.body[-1] == "Added line."
    fan_side = client.get(f"/api/v1/stories/{uid('story', row['id'] + ':en')}").json()
    assert fan_side["corrected_at"] and fan_side["body"].endswith("Added line.")
    again = ed.get("/stories", params={"corrected": "yes"}).json()["items"]
    assert row["id"] in [i["id"] for i in again]
    fresh = ed.get(f"/review-queue/fix-{row['id']}").json()
    assert fresh["status"] == "pending" and fresh["history"][-1]["action"] == "corrected"


# ---- P4 event management / P5 news and content ---------------------------------------------

def test_event_manage_overview_settings_visibility():
    pub = _publisher()
    assert _club_admin().get("/tournaments/njc-u17").status_code == 403
    d = pub.get("/tournaments/njc-u17").json()
    assert d["kind"] == "managed" and d["tournamentId"] == "njc-u17" and d["counts"]["total"] == len(d["matches"])
    assert d["settings"]["canPublish"] is False and d["junior"] is True
    assert {s["email"]: s["status"] for s in d["scorers"]}["jari.niemi@tarmo.fi"] == "active"
    njc11 = next(m for m in d["matches"] if m["match"]["id"] == "njc11")
    assert njc11["scorer"]["name"] == "Jari Niemi" and njc11["editable"]
    assert len(d["teams"]) == 8 and all(t["group"] for t in d["teams"])
    # draft events still give the wizard's setup
    assert "kind" not in pub.get("/tournaments/winter-futsal-26").json()
    assert pub.patch("/tournaments/njc-u17", json={"name": "New name"}).json()["detail"]["code"] == "published"
    s = pub.patch("/tournaments/njc-u17", json={"languages": ["fi", "en", "bn"], "reviewEnabled": False, "visibility": "unlisted"}).json()
    assert s["settings"] == {"languages": ["fi", "en", "bn"], "reviewEnabled": False, "visibility": "unlisted", "canPublish": False}
    fan = _fresh_client()
    njc = uid("tournament", "njc-u17")
    assert njc not in [t["id"] for t in fan.get("/api/v1/tournaments?limit=100").json()["items"]]
    assert fan.get(f"/api/v1/tournaments/{njc}").status_code == 200
    pub.patch("/tournaments/njc-u17", json={"visibility": "hidden"})
    assert fan.get(f"/api/v1/tournaments/{njc}").status_code == 404


def test_event_fixtures_results_scorers():
    from app.main import store

    pub = _publisher()
    d = pub.get("/tournaments/njc-u17").json()
    later = store.now + 26 * 3_600_000
    bad = pub.post("/tournaments/njc-u17/matches", json={"home": "olsu17", "away": "olsu17", "startsAt": later, "venue": "Raatti"})
    assert bad.status_code == 422
    assert pub.post("/tournaments/njc-u17/matches", json={"home": "olsu17", "away": "kemi", "startsAt": later, "venue": "Raatti"}).status_code == 422
    nm = pub.post("/tournaments/njc-u17/matches", json={"home": "olsu17", "away": "torniou17", "startsAt": later, "venue": "Raatti Stadium",
                                                        "group": "Semi-final"}).json()
    assert nm["match"]["stage"] == "Semi-final" and nm["status"] == "upcoming"
    clash = pub.post("/tournaments/njc-u17/matches", json={"home": "olsu17", "away": "acou17", "startsAt": later + 600_000, "venue": "Elsewhere"})
    assert clash.json()["detail"]["code"] == "clash"
    mid = nm["match"]["id"]
    e = pub.patch(f"/matches/{mid}", json={"startsAt": later + 3_600_000, "venue": "Heinäpää", "dataLevel": "results_only"}).json()
    assert e["match"]["venue"] == "Heinäpää" and e["match"]["dataLevel"] == "results_only"
    assert pub.patch(f"/matches/{mid}", json={"scorerId": "es-404"}).json()["detail"]["code"] == "not_a_scorer"
    assert pub.patch(f"/matches/{mid}", json={"scorerId": "es-1"}).json()["scorer"]["name"] == "Jari Niemi"
    assert pub.patch(f"/matches/{mid}", json={"score": [1, 0]}).json()["detail"]["code"] == "not_started"
    # live game: enter the result
    live = next(m for m in d["matches"] if m["status"] == "live")
    fin = pub.patch(f"/matches/{live['match']['id']}", json={"score": [2, 2]}).json()
    assert fin["status"] == "finished" and fin["match"]["score"] == [2, 2]
    cor = pub.patch(f"/matches/{live['match']['id']}", json={"score": [2, 1]}).json()
    assert cor["match"]["score"] == [2, 1] and "2–2 → 2–1" in cor["match"]["correction"]["message"]
    assert pub.patch(f"/matches/{live['match']['id']}", json={"venue": "X Y"}).json()["detail"]["code"] == "started"
    assert pub.delete(f"/matches/{mid}").status_code == 204
    assert pub.delete(f"/matches/{live['match']['id']}").status_code == 409
    # other publishers' / clubs' matches go the club way
    # scorer invites
    r = pub.post("/tournaments/njc-u17/scorer-invites", json={"emails": ["new.scorer@example.org", "nope", "jari.niemi@tarmo.fi"]}).json()
    assert [i["email"] for i in r["invited"]] == ["new.scorer@example.org"] and len(r["skipped"]) == 2
    # (scoring itself is v1 now: a scorer pass or an organiser account, see tests/test_v1.py)
    es2 = pub.delete("/tournaments/njc-u17/scorers/es-2").json()
    assert "es-2" not in [s["id"] for s in es2["scorers"]]


def test_event_content_posts():
    from app.main import store

    pub = _publisher()
    d = pub.get("/tournaments/njc-u17/stories").json()
    assert d["counts"]["in_review"] >= 2 and d["counts"]["published"] > 0 and d["canPublish"] is False
    assert all(i["status"] == "published" for i in pub.get("/tournaments/njc-u17/stories", params={"status": "published"}).json()["items"])
    post = {"eventId": "njc-u17", "title": "Semi-final tickets on sale", "body": "Tickets are **free** for juniors.\n\n- Gates open 11:00\n- Bring water",
            "teamIds": ["olsu17"], "matchIds": ["njc11"], "language": "fi"}
    assert pub.post("/stories", json={**post, "language": "bn"}).json()["detail"]["code"] == "language"
    assert pub.post("/stories", json={**post, "teamIds": ["kemi"]}).json()["detail"]["code"] == "teams"
    dr = pub.post("/stories", json={**post, "submit": False}).json()
    assert dr["status"] == "draft" and dr["editable"] and dr["summary"] == "Tickets are free for juniors."
    ed = pub.patch(f"/stories/{dr['id']}", json={"title": "Semi-final day: what to know"}).json()
    assert ed["status"] == "draft" and ed["title"] == "Semi-final day: what to know"
    sent = pub.patch(f"/stories/{dr['id']}", json={"submit": True}).json()
    assert sent["status"] == "in_review"  # no publish rights on the junior cup -> editor desk
    editor = _editor()
    q = editor.get("/review-queue", params={"reason": "manual_news"}).json()["items"]
    item = next(i for i in q if i["headline"] == "Semi-final day: what to know")
    assert item["source"] == "Oulu Sport Events"
    assert pub.patch(f"/stories/{dr['id']}", json={"title": "Semi-final day: all you need"}).json()["status"] == "in_review"
    editor.post(f"/review-queue/{item['id']}/claim")
    assert pub.patch(f"/stories/{dr['id']}", json={"title": "Too late now"}).json()["detail"]["code"] == "in_review"
    editor.post(f"/stories/{dr['id']}/reject", json={"reason": "Ticket info must come from the venue"})
    blocked = pub.get("/tournaments/njc-u17/stories", params={"status": "blocked"}).json()["items"]
    assert blocked[0]["id"] == dr["id"] and "venue" in blocked[0]["note"]
    # with publish rights (oulu-sixes): published now, or scheduled
    six = {"eventId": "oulu-sixes", "title": "Final day schedule", "body": "Play starts at 10.", "language": "en"}
    p1 = pub.post("/stories", json=six).json()
    assert p1["status"] == "published"
    fan_side = _fresh_client().get(f"/api/v1/stories/{uid('story', p1['id'] + ':en')}").json()
    assert fan_side["headline"] == "Final day schedule"
    p2 = pub.post("/stories", json={**six, "title": "See you tomorrow", "publishAt": store.now + 3_600_000}).json()
    assert p2["status"] == "scheduled"
    assert _fresh_client().get(f"/api/v1/stories/{uid('story', p2['id'] + ':en')}").status_code == 404
    assert pub.patch(f"/stories/{p1['id']}", json={"body": "Play starts at 11."}).json()["body"] == ["Play starts at 11."]
    assert pub.patch("/stories/r1-report", json={"title": "Not mine"}).json()["detail"]["code"] == "not_your_post"


def test_event_scorer_invite_activates_on_sign_in():
    pub = _publisher()
    pub.post("/tournaments/njc-u17/scorer-invites", json={"emails": ["volunteer@example.org"], "name": "Vera"})
    sid = next(s["id"] for s in pub.get("/tournaments/njc-u17").json()["scorers"] if s["email"] == "volunteer@example.org")
    pub.patch("/matches/njc12", json={"scorerId": sid})
    c = _fresh_client()
    _member_account(c, "volunteer@example.org")
    _v1(c)
    assert c.get("/api/v1/me").status_code == 200  # signing in activates the invite
    assert next(s for s in pub.get("/tournaments/njc-u17").json()["scorers"] if s["id"] == sid)["status"] == "active"


def test_published_event_rules_page():
    pub = _publisher()
    q = pub.get("/review-queue", params={"scope": "mine"}).json()
    assert {i["eventId"] for i in q["items"]} == {"njc-u17"}
    s = pub.get("/tournaments/njc-u17/rules/summary").json()
    assert s["state"] == "confirmed" and [v["version"] for v in s["versions"]] == [1, 2]
    assert s["draft"]["points"] == {"win": 3, "draw": 1, "loss": 0} and s["draft"]["tiebreakers"][0] == "goal_difference"
    assert pub.get("/tournaments/njc-u17/rules/status").status_code == 200
    six = pub.get("/tournaments/oulu-sixes/rules/summary").json()
    assert six["state"] == "confirmed" and six["draft"]["tiebreakers"][0] == "net_run_rate"
    assert _club_admin().get("/tournaments/njc-u17/rules/summary").status_code == 403
