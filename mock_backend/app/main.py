import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager

import re
import secrets
from urllib.parse import unquote

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from . import club_portal
from . import club_members
from . import editor_desk
from . import review_item
from . import event_manage
from . import event_content
from . import published
from . import rules_review
from . import event_setup
from . import publisher
from . import scoring
from . import corrections
from . import billing
from . import club_profile
from . import club_matches as matches_admin
from . import club_teams as teams_admin
from .mock_data import CLUBS, INVITE_CODES, ROLE_LABELS
from .models import (
    EditorQueue, QueueItem, EventManage, ManagedMatch, FixtureIn, ScorerInvite, ScorerInviteResult, EventStories, EventStory, PostIn, PostPatch, EditorCorrections, PublishedPage, PublishedStory, UnpublishRequest, StoryEdit, ReviewTarget, ApproveRequest, RejectRequest, RegenerateRequest,
    RulesDraftPatch,
    EventBasics, EventPatch, EventSetup, FixtureImport, FixtureImportResult, RulesStatus, TeamAdd,
    PublisherEvents, ReviewQueue,
    CorrectionIn, CorrectionItem, CorrectionList, CorrectionResolve,
    BillingSummary, PortalRequest, PortalSession, SeatChange, SeatChangeResult,
    ClubPatch, ClubProfile, Sponsor, SponsorIn, SponsorPatch, Upload,
    FinishMatch, MatchPatch, PortalMatch, PortalMatches,
    ClubTeams, ConsentIn, FamilyIn, PlayerIn, PlayerPatch, RosterPlayer, TeamIn, TeamPatch, TeamRoster, TeamSummary,
    BulkInviteIn, BulkInviteResult, ClubMembers, MemberChange, MemberPatch,
    Me, RedeemCode,
    InviteAccepted, InviteInfo, InviteOffer,
    ClubDashboard,
    Team,
)
from .store import Session

TICK_SECONDS = float(os.getenv("OURSPORT_TICK_SECONDS", "4"))
SIMULATE = os.getenv("OURSPORT_SIMULATE", "1") != "0"
# No email service yet: in dev the password-reset link is returned to the page (and always logged).
DEV_EMAIL = os.getenv("OURSPORT_DEV_EMAIL", "1") != "0"
CORS_ORIGINS = os.getenv("OURSPORT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

from .main_store import store  # noqa: E402  (shared with the v1 routes)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(store.run_ticker(TICK_SECONDS)) if SIMULATE else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="OurSport API (mock)", version="0.1.0", lifespan=lifespan,
              openapi_url="/api/v1/openapi.json", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,  # session cookie when the frontend runs on another origin
    allow_methods=["*"],
    allow_headers=["*"],
)

# The OurSport API v1 contract (backend/docs/05-api.md). The routes below it are the older
# mock-only API of the areas not moved to v1 yet (club portal, publisher, editor desk).
from .v1 import errors as v1_errors  # noqa: E402
from .v1.live import router as v1_live  # noqa: E402
from .v1.routes import mock_router as v1_mock  # noqa: E402
from .v1.routes import router as v1_router  # noqa: E402

v1_errors.install(app)
app.include_router(v1_router)
app.include_router(v1_live)
app.include_router(v1_mock)


@app.get("/health/live", tags=["health"])
def health_live() -> dict:
    """The process is up."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def health_ready() -> dict:
    """Ready to serve (the mock has no database or Redis)."""
    return {"status": "ok", "checks": {}}


# ---- Session, me & follows ---------------------------------------------------

SESSION_COOKIE = "lp_sid"


def get_session(request: Request, response: Response) -> Session:
    """Cookie-based session per browser; created on first use (visitors too)."""
    session = store.session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        session = store.new_session(secrets.token_urlsafe(16))
        response.set_cookie(SESSION_COOKIE, session.id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
    return session


# ---- Sign up / log in / reset password (F12) ------------------------------------------

# ---- Account & subscription (F10): members only ------------------------------------

def _require_member(session: Session = Depends(get_session)) -> Session:
    if not session.signed_in:
        raise HTTPException(401, "Sign in to manage your account.")
    return session


@app.post("/api/me/redeem-code", response_model=Me)
def redeem_code(body: RedeemCode, session: Session = Depends(_require_member)):
    """Invite code from a club: grants Premium "via" that club until the end of the season."""
    club_id = INVITE_CODES.get(body.code.strip().upper())
    if club_id is None:
        raise HTTPException(400, {"code": "invalid_code", "message": "That code isn’t valid. Check it with your club."})
    session.grant_premium(club_id)
    return session.me()


# ---- Following page (F9): members only ----------------------------------------------

# ---- Player page (F8) -----------------------------------------------------------

# ---- Notifications (F11) -----------------------------------------------------------

# ---- News feed (right column) ---------------------------------------------------------

# ---- Accept invite (F13) -----------------------------------------------------------------

def _invite_info(token: str, inv: dict, session: Session) -> InviteInfo:
    club = CLUBS[inv["club"]]
    if inv["kind"] == "premium_seat":
        offer = InviteOffer(kind="premium_seat", label="Premium seat",
                            description="Live scores, live timelines and “if it ends like this” stakes for every match, "
                                        f"granted by {club.name} for the season.")
    else:
        label, desc = ROLE_LABELS[inv["role"]]
        offer = InviteOffer(kind="role", role=inv["role"], label=label, description=desc)
    if inv["used_by"] is not None:
        status = "accepted_by_you" if inv["used_by"] is session else "used"
    elif inv["expires_at"] < store.now:
        status = "expired"
    else:
        status = "valid"
    return InviteInfo(token=token, club=club, offer=offer, invited_by=inv["invited_by"], message=inv["message"],
                      expires_at=inv["expires_at"], status=status)


def _invite_or_404(token: str) -> dict:
    inv = store.invites.get(token)
    if inv is None:
        raise HTTPException(404, {"code": "invalid", "message": "This invite link isn’t valid."})
    return inv


@app.get("/api/invites/{token}", response_model=InviteInfo)
def get_invite(token: str, session: Session = Depends(get_session)):
    """Anyone with the link: which club invites you, what is offered, and whether the link still works."""
    return _invite_info(token, _invite_or_404(token), session)


@app.post("/api/invites/{token}/accept", response_model=InviteAccepted)
def accept_invite(token: str, session: Session = Depends(_require_member)):
    """Accept (members). A premium seat grants Premium via the club; a role adds it to the account.
    Either way the member follows the club. Single use."""
    inv = _invite_or_404(token)
    info = _invite_info(token, inv, session)
    if info.status == "accepted_by_you":
        return InviteAccepted(me=session.me(), invite=info)
    if info.status != "valid":
        raise HTTPException(410, {"code": info.status, "message": "This invite has expired or was already used."})
    if inv.get("member"):  # invite from the club's member list (C2): premium and/or role as set there
        club_members.accept(store, inv, session)
    elif inv["kind"] == "premium_seat":
        session.grant_premium(inv["club"])
    elif (inv["club"], inv["role"]) not in session.roles:
        session.roles.append((inv["club"], inv["role"]))
    if inv["club"] not in session.clubs:
        session.clubs.append(inv["club"])
    inv["used_by"] = session
    return InviteAccepted(me=session.me(), invite=_invite_info(token, inv, session))


# ---- Club portal (C-series): club admins only --------------------------------------------

def club_admin(club_id: str, session: Session = Depends(get_session)) -> Session:
    """401 if not signed in, 404 for an unknown club, 403 if not an admin of this club."""
    if not session.signed_in:
        raise HTTPException(401, "Log in with your club admin account.")
    if club_id not in CLUBS:
        raise HTTPException(404, "Club not found")
    if not session.is_admin(club_id):
        raise HTTPException(403, {"code": "not_club_admin", "message": "You’re not an admin of this club."})
    return session


@app.get("/clubs/{club_id}/dashboard", response_model=ClubDashboard)
def club_dashboard(club_id: str, session: Session = Depends(club_admin)):
    """C1: KPI tiles (followers, Premium seats used/total, matches this week, open corrections),
    next matches with their scorer (or none), latest published stories about the club."""
    return club_portal.dashboard(store, club_id)


@app.get("/clubs/{club_id}/teams", response_model=ClubTeams)
def list_club_teams(club_id: str, session: Session = Depends(club_admin)):
    """C3: the club's teams with sport, age group, competitions and squad counts (plus sport / age group options)."""
    return teams_admin.club_teams(store, club_id)


@app.post("/clubs/{club_id}/teams", response_model=TeamSummary, status_code=201)
def create_club_team(club_id: str, body: TeamIn, session: Session = Depends(club_admin)):
    """Add a team. 409 `team_exists` for a name the club already uses."""
    return teams_admin.create_team(store, club_id, body)


@app.patch("/clubs/{club_id}/teams/{team_id}", response_model=Team)
def update_club_team(club_id: str, team_id: str, body: TeamPatch, session: Session = Depends(club_admin)):
    team = teams_admin.team_for_admin(team_id, session)
    if team.club_id != club_id:
        raise HTTPException(404, "Team not found")
    return teams_admin.update_team(store, team, body)


@app.get("/teams/{team_id}/players", response_model=TeamRoster)
def team_players(team_id: str, session: Session = Depends(get_session)):
    """C3 roster (admins of the team's club): number, birth year, visibility, consent and family links.
    `allowed` on each player lists the visibilities the API accepts right now."""
    return teams_admin.team_roster(store, teams_admin.team_for_admin(team_id, session))


@app.post("/teams/{team_id}/players", response_model=RosterPlayer, status_code=201)
def add_team_player(team_id: str, body: PlayerIn, session: Session = Depends(get_session)):
    """Add a player. Under-18s default to hidden; 409 `consent_required` for a visibility that needs consent,
    409 `number_taken`."""
    return teams_admin.add_player(store, teams_admin.team_for_admin(team_id, session), body)


@app.patch("/teams/{team_id}/players/{player_id}", response_model=RosterPlayer)
def update_team_player(team_id: str, player_id: str, body: PlayerPatch, session: Session = Depends(get_session)):
    """Edit a player or change the visibility. 409 `consent_required` (with `allowed`), 409 `number_taken`."""
    player = teams_admin.player_for_admin(player_id, session)
    if player.team.id != team_id:
        raise HTTPException(404, "Player not found")
    return teams_admin.update_player(store, player, body)


@app.post("/players/{player_id}/consent", response_model=RosterPlayer)
def record_player_consent(player_id: str, body: ConsentIn, session: Session = Depends(get_session)):
    """Record consent (scope `family` or `public`). For under-18s it must come from a guardian; with
    `linkFamily` the guardian's account is linked to the player too."""
    return teams_admin.record_consent(store, teams_admin.player_for_admin(player_id, session), body, session)


@app.delete("/players/{player_id}/consent", response_model=RosterPlayer)
def withdraw_player_consent(player_id: str, session: Session = Depends(get_session)):
    """Consent withdrawn: the profile falls back to hidden if its visibility needed the consent."""
    return teams_admin.withdraw_consent(store, teams_admin.player_for_admin(player_id, session))


@app.post("/players/{player_id}/family", response_model=RosterPlayer)
def link_player_family(player_id: str, body: FamilyIn, session: Session = Depends(get_session)):
    """Link a family member (by email) to a player under 18. Works right away if they have an account,
    otherwise when they sign up."""
    return teams_admin.link_family(store, teams_admin.player_for_admin(player_id, session), body)


@app.delete("/players/{player_id}/family/{link_id}", response_model=RosterPlayer)
def unlink_player_family(player_id: str, link_id: str, session: Session = Depends(get_session)):
    return teams_admin.unlink_family(store, teams_admin.player_for_admin(player_id, session), link_id)


@app.get("/publisher/events", response_model=PublisherEvents)
def publisher_events(session: Session = Depends(get_session)):
    """P1: the publisher's events with status (draft, rules_pending, scheduled, live, finished), progress and the
    next step. 403 `not_publisher`."""
    return publisher.events(store, session)


@app.post("/tournaments", response_model=EventSetup, status_code=201)
def create_tournament(body: EventBasics, session: Session = Depends(get_session)):
    """P2 step 1: create a draft event (name, sport, dates, venues, age group, content languages, logo)."""
    return event_setup.create(store, body, session)


@app.get("/tournaments/{event_id}", response_model=EventSetup | EventManage)
def get_tournament_setup(event_id: str, session: Session = Depends(get_session)):
    """The owner only. Not published yet: the wizard's saved draft (EventSetup; continue at /publisher/events/{id}/setup).
    Published (P4, `kind: "managed"`): status, counts, groups, teams with standings, every match with status, scorer and
    data level, the event's scorers and its settings (content languages, publisher review, visibility, publish rights)."""
    e = event_manage.owned_event(store, event_id, session)
    if e.get("tournament_id"):
        return event_manage.manage(store, event_id, e)
    event_setup.owned(store, event_id, session)
    return event_setup.setup(store, event_id)


@app.patch("/tournaments/{event_id}", response_model=EventSetup | EventManage)
def patch_tournament(event_id: str, body: EventPatch, session: Session = Depends(get_session)):
    """Save wizard changes: basics, groups, team groups, fixtures (whole list, 422 with per-row `problems`) or
    `step` (marks a step done if its required fields are valid; 422 otherwise)."""
    e = event_manage.owned_event(store, event_id, session)
    fields = set(body.model_fields_set)
    if e.get("tournament_id"):  # published (P4): settings only
        return event_manage.patch(store, event_id, e, body, fields)
    e = event_setup.owned(store, event_id, session)
    if "review_enabled" in fields and body.review_enabled is not None:
        e["review_enabled"] = body.review_enabled
    if "visibility" in fields and body.visibility:
        e["visibility"] = body.visibility
    return event_setup.update(store, event_id, e, body, fields - {"review_enabled", "visibility"})


@app.post("/tournaments/{event_id}/matches", response_model=ManagedMatch, status_code=201)
def add_event_match(event_id: str, body: FixtureIn, session: Session = Depends(get_session)):
    """P4: add a fixture to a published event (teams of the event, future start). 409 `clash` when a team or the
    venue is already busy within 30 minutes."""
    return event_manage.add_match(store, session, event_id, body)


@app.post("/tournaments/{event_id}/scorer-invites", response_model=ScorerInviteResult, status_code=201)
def invite_event_scorers(event_id: str, body: ScorerInvite, session: Session = Depends(get_session)):
    """P4: invite scorers by email (`emails`, optional `name` for one, `message`). An invite turns active when someone
    signs in with that email and opens the scorer area (/score); it expires after 14 days. Inviting again resends."""
    return event_manage.invite_scorers(store, session, event_id, body)


@app.delete("/tournaments/{event_id}/scorers/{scorer_id}", response_model=EventManage)
def remove_event_scorer(event_id: str, scorer_id: str, session: Session = Depends(get_session)):
    """P4: remove a scorer (or cancel the invite); they are taken off matches that haven't finished."""
    return event_manage.remove_scorer(store, session, event_id, scorer_id)


@app.get("/tournaments/{event_id}/stories", response_model=EventStories)
def event_stories(
    event_id: str,
    status: str | None = Query(None, pattern="^(draft|scheduled|in_review|published|blocked|unpublished)$"),
    author: str | None = Query(None, pattern="^(ai|manual)$"),
    language: str | None = Query(None, pattern="^(fi|en|bn)$"),
    q: str | None = Query(None, max_length=80),
    session: Session = Depends(get_session),
):
    """P5: every story about the event (AI and manual) with its status: draft, scheduled, in_review, published,
    blocked (rejected by an editor, with the reason) or unpublished. Plus the teams, matches and content languages for
    the editor, and `canPublish` (without it, manual posts go to the editor desk first)."""
    return event_content.stories(store, session, event_id, status=status, author=author, language=language, q=q)


@app.post("/stories", response_model=EventStory, status_code=201)
def create_post(body: PostIn, session: Session = Depends(get_session)):
    """P5: a manual post for an event. `submit: false` saves a draft. Sent: published now or at `publishAt` with publish
    rights; otherwise it goes to the editor desk (manual news) and comes out when approved."""
    return event_content.create(store, session, body)


@app.post("/tournaments/{event_id}/teams", response_model=EventSetup, status_code=201)
def add_tournament_team(event_id: str, body: TeamAdd, session: Session = Depends(get_session)):
    """Add an existing OurSport team (`teamId`, same sport) or a new one (`name`, `short`)."""
    e = event_setup.owned(store, event_id, session)
    return event_setup.add_team(store, event_id, e, body)


@app.delete("/tournaments/{event_id}/teams/{team_id}", response_model=EventSetup)
def remove_tournament_team(event_id: str, team_id: str, session: Session = Depends(get_session)):
    e = event_setup.owned(store, event_id, session)
    return event_setup.remove_team(store, event_id, e, team_id)


@app.post("/tournaments/{event_id}/import", response_model=FixtureImportResult)
def import_tournament_fixtures(event_id: str, body: FixtureImport, session: Session = Depends(get_session)):
    """Fixtures from a CSV (date, time, home, away, venue, group) or a generated round robin. `dryRun` previews;
    otherwise all rows or none (422 with per-row `problems`)."""
    e = event_setup.owned(store, event_id, session)
    return event_setup.import_fixtures(store, event_id, e, body)


@app.post("/tournaments/{event_id}/rulebook", response_model=EventSetup, status_code=202)
async def upload_rulebook(event_id: str, request: Request, session: Session = Depends(get_session)):
    """Rulebook: the file itself as the body (PDF or DOCX, `X-Filename` header), or JSON `{url}` / `{text}`.
    Starts reading the rules; poll GET /tournaments/{id}/rules/status. Needs teams and fixtures first."""
    e = event_setup.owned(store, event_id, session)
    ctype = request.headers.get("content-type", "")
    if int(request.headers.get("content-length") or 0) > event_setup.MAX_RULEBOOK:
        raise HTTPException(413, {"code": "too_large", "message": "The rulebook can be at most 10 MB."})
    data = await request.body()
    if ctype.startswith("application/json"):
        body = json.loads(data or b"{}")
        url, text = (body.get("url") or "").strip(), (body.get("text") or "").strip()
        if url:
            if not re.match(r"^https?://\S+\.\S+", url):
                raise HTTPException(422, {"code": "url", "message": "Paste a full link (https://…)."})
            return event_setup.start_rules(store, event_id, e, "url", url, None, "")  # the demo doesn't fetch links
        if len(text) < 20:
            raise HTTPException(422, {"code": "text", "message": "Paste the rules text (at least a few sentences)."})
        return event_setup.start_rules(store, event_id, e, "text", "Pasted text", len(text), text[:200_000])
    if not data:
        raise HTTPException(422, {"code": "file", "message": "The file is empty."})
    name = unquote(request.headers.get("x-filename", "rulebook"))[:120]
    text = event_setup.rulebook_text(ctype, name, data)
    return event_setup.start_rules(store, event_id, e, "file", name, len(data), text)


def _rules_event(event_id: str, session: Session) -> dict:
    """P3 rules pages: an event being set up, or a published one (its confirmed rules, editable as a new version)."""
    e = event_manage.owned_event(store, event_id, session)
    if e.get("tournament_id"):
        return event_manage.ensure_rules(store, e)
    return event_setup.owned(store, event_id, session)


@app.get("/tournaments/{event_id}/rules/status", response_model=RulesStatus)
def tournament_rules_status(event_id: str, session: Session = Depends(get_session)):
    """Rules reading progress (`reading` 0–100 with the current step), then `done` with the rules for P3."""
    e = _rules_event(event_id, session)
    return event_setup.rules_status(store, e)


def _camel(obj, keep=("draft", "answers")):
    """camelCase keys for the rules summary (its draft and answers keep their rule keys / question ids)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ck = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k) if isinstance(k, str) else k
            out[ck] = v if k in keep else _camel(v, keep)
        return out
    if isinstance(obj, list):
        return [_camel(x, keep) for x in obj]
    return obj


@app.get("/tournaments/{event_id}/rules/summary")
def tournament_rules_summary(event_id: str, session: Session = Depends(get_session)):
    """P3: the rules draft as cards (plain language, source quote, edit fields), questions from the AI, worked examples
    computed by the engine with their marks, edge-case tests, blockers, rule versions. `state`: reading / failed / draft /
    confirmed / none."""
    e = _rules_event(event_id, session)
    return _camel(rules_review.summary(store, event_id, e))


@app.patch("/tournaments/{event_id}/rules/draft")
def tournament_rules_draft(event_id: str, body: RulesDraftPatch, session: Session = Depends(get_session)):
    """Change rule values, answer questions, mark examples (`incorrect` needs a note) or start a manual draft.
    Returns the new summary (examples and tests recomputed; marks of changed examples reset)."""
    e = _rules_event(event_id, session)
    rules_review.patch(store, e, body)
    return _camel(rules_review.summary(store, event_id, e))


@app.post("/tournaments/{event_id}/rules/confirm")
def tournament_rules_confirm(event_id: str, session: Session = Depends(get_session)):
    """Confirm the draft as a new rule version. 409 `not_ready` with `blockers` (questions, examples, failing tests)."""
    e = _rules_event(event_id, session)
    version = rules_review.confirm(store, e, session)
    event_manage.apply_confirmed_rules(store, e)
    return _camel({"version": version, "summary": rules_review.summary(store, event_id, e)})


@app.post("/tournaments/{event_id}/rules/retry", response_model=EventSetup, status_code=202)
def tournament_rules_retry(event_id: str, session: Session = Depends(get_session)):
    """Read the same rulebook again (after `failed`)."""
    e = event_setup.owned(store, event_id, session)
    if not e.get("rulebook"):
        raise HTTPException(409, {"code": "no_rulebook", "message": "Upload the rulebook first."})
    rb = e["rulebook"]
    return event_setup.start_rules(store, event_id, e, rb["kind"], rb["name"], rb.get("size"), e.get("rules_text", ""))


@app.get("/review-queue", response_model=ReviewQueue | EditorQueue)
def review_queue(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    reason: str | None = Query(None, pattern="^(sensitive_topic|blocked_claim|junior_mention|manual_news|correction)$"),
    sport: str | None = Query(None, max_length=30),
    event: str | None = Query(None, max_length=60),
    language: str | None = Query(None, pattern="^(fi|en|bn)$"),
    age: str | None = Query(None, pattern="^(under_30|over_30|over_120)$"),
    assigned: str | None = Query(None, pattern="^(me|none)$"),
    cursor: str | None = Query(None, max_length=10),
    limit: int = Query(25, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """Items waiting for review.
    Editors (E1, the default `scope=all` for them): AI texts the checker flagged, club news and open corrections,
    high priority first, then the longest-waiting. Filters: reason, sport, event, language, age (minutes waiting),
    assigned (me / none); `cursor` pages. Publishers (`scope=mine`, P1): AI texts for their events with publisher review on."""
    if scope == "mine" or (scope is None and not session.is_editor()):
        return publisher.review_queue(store, session, "mine")
    return editor_desk.queue(store, session, reason=reason, sport=sport, event=event, language=language, age=age,
                             assigned=assigned, cursor=cursor, limit=limit)


@app.get("/review-queue/{item_id}")
def review_item_detail(item_id: str, session: Session = Depends(get_session)):
    """E2: one item — the text with the checker's marks (sentences tied to fact ids, red flags with reasons), the fact sheet,
    match data, rule version, history and the previous/next item in queue order. `check.status`: passed / flagged / stale."""
    return _camel(review_item.detail(store, session, item_id), keep=())


@app.post("/review-queue/{item_id}/claim", response_model=QueueItem)
def claim_review_item(item_id: str, force: bool = False, session: Session = Depends(get_session)):
    """Assign an item to me. `next` takes the oldest high-priority item nobody has (404 `empty`).
    409 `claimed` if another editor has it (`force=true` takes it over)."""
    return editor_desk.claim(store, session, item_id, force)


@app.get("/stories", response_model=PublishedPage)
def editor_stories(
    status: str = Query("published", pattern="^(published|unpublished|all)$"),
    q: str | None = Query(None, max_length=80),
    date: str | None = Query(None, pattern="^(24h|7d|30d)$"),
    event: str | None = Query(None, max_length=60),
    author: str | None = Query(None, pattern="^(ai|manual)$"),
    corrected: str | None = Query(None, pattern="^(yes|no|reported)$"),
    cursor: str | None = Query(None, max_length=10),
    limit: int = Query(30, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """E3 (editors): published stories, newest first. `q` searches headline and summary; `date` 24h / 7d / 30d;
    `author` ai / manual; `corrected` yes / no / reported (has an open error report). Each row has `correctItemId`,
    the E2 item that "Correct" opens."""
    return published.stories(store, session, status=status, q=q, date=date, event=event, author=author,
                             corrected=corrected, cursor=cursor, limit=limit)


@app.post("/stories/{story_id}/unpublish", response_model=PublishedStory)
def unpublish_story(story_id: str, body: UnpublishRequest, session: Session = Depends(get_session)):
    """E3: take a story off OurSport (reason required, kept for the record). 409 `unpublished` if already off."""
    return published.unpublish(store, session, story_id, body.reason)


@app.patch("/stories/{story_id}")
def edit_story(story_id: str, payload: dict = Body(...), session: Session = Depends(get_session)):
    """E2: save the editor's changes to the text under review (the live story changes only on approve). Marks the
    checker result stale. 409 `stale_version` if someone saved meanwhile, `claimed` if another editor has it.
    Publishers (P5): change their own post (PostPatch: title, summary, body, imageUrl, teamIds, matchIds, language,
    publishAt; `submit: true` sends a draft). Posts in review can change until an editor picks them up."""
    from pydantic import ValidationError

    try:
        if session.signed_in and session.is_publisher() and not session.is_editor():
            post = PostPatch.model_validate(payload)
            return event_content.update(store, session, story_id, post, post.model_fields_set).model_dump(by_alias=True)
        body = StoryEdit.model_validate(payload)
    except ValidationError as err:
        raise HTTPException(422, [{"msg": e["msg"], "loc": e["loc"]} for e in err.errors()]) from None
    return _camel(review_item.patch(store, session, story_id, body), keep=())


@app.post("/stories/{story_id}/check")
def check_story(story_id: str, body: ReviewTarget | None = None, session: Session = Depends(get_session)):
    """E2: re-run the checker on the current text: numbers not in the fact sheet, junior players, unsupported claims,
    sensitive topics."""
    return _camel(review_item.check(store, session, story_id, body.item_id if body else None), keep=())


@app.post("/stories/{story_id}/approve")
def approve_story(story_id: str, body: ApproveRequest, session: Session = Depends(get_session)):
    """E2: approve and publish. 409 `check_stale` (edited since the last check), `red_flags` (unless `verified` and a
    note of 10+ characters — logged), `claimed`, `decided`. Corrections: updates the story and marks the report fixed."""
    return _camel(review_item.approve(store, session, story_id, body), keep=())


@app.post("/stories/{story_id}/reject")
def reject_story(story_id: str, body: RejectRequest, session: Session = Depends(get_session)):
    """E2: reject with a reason (required). Drafts are dropped; corrections are marked rejected."""
    return _camel(review_item.reject(store, session, story_id, body), keep=())


@app.post("/stories/{story_id}/regenerate")
def regenerate_story(story_id: str, body: RegenerateRequest, session: Session = Depends(get_session)):
    """E2: send back to the AI writer with a note. The new version returns to the queue a few seconds later (mock)."""
    return _camel(review_item.regenerate(store, session, story_id, body), keep=())


@app.get("/corrections", response_model=CorrectionList | EditorCorrections)
def list_corrections(
    club: str | None = Query(None, description="club id (C7, club admins)"),
    status: str = Query("open", pattern="^(open|fixed|rejected|all)$"),
    session: Session = Depends(get_session),
):
    """C7 (`club=`): error reports about the club's matches and stories, from fans (anonymous) and from the club,
    with status open / fixed / rejected and the editor's note. Club admins only.
    E3 (no `club`, editors): every report with `status` (default open, oldest first), the story or match it is about,
    and the E2 item to open it in."""
    if club is None:
        return published.correction_list(store, session, status)
    club_admin(club, session)
    return corrections.list_for(store, club)


@app.post("/corrections", response_model=CorrectionItem, status_code=201)
def report_correction(body: CorrectionIn, session: Session = Depends(get_session)):
    """A club reports an error: `{clubId, matchId, field, message, correctValue}`. Editors fix or reject it.
    422 for a match that isn't the club's, 409 `duplicate` for the same open correction."""
    if not session.signed_in:
        raise HTTPException(401, "Log in with your club admin account.")
    return corrections.report(store, body, session)


@app.patch("/corrections/{correction_id}", response_model=CorrectionItem)
def resolve_correction(correction_id: str, body: CorrectionResolve, session: Session = Depends(get_session)):
    """E3: resolve a report without editing: `fixed` (fans see a "Corrected" tag on the match) or `rejected`
    (note required — the club sees it). 409 `resolved` if it isn't open any more."""
    return published.resolve(store, session, correction_id, body.status, body.note)


@app.get("/clubs/{club_id}/billing", response_model=BillingSummary)
def club_billing(club_id: str, session: Session = Depends(club_admin)):
    """C6: plan, seats (total / in use), price per seat, next invoice date and estimate, payment method summary
    (from the provider), invoices."""
    return billing.summary(store, club_id)


@app.post("/clubs/{club_id}/billing/seats", response_model=SeatChangeResult)
def change_club_seats(club_id: str, body: SeatChange, session: Session = Depends(club_admin)):
    """Change the number of Premium seats (`preview: true` only prices it). Adding seats charges the rest of this
    month on the next invoice. 409 `seats_in_use` below the seats in use, 402 `payment_method_required`."""
    return billing.change_seats(store, club_id, body.seats, body.preview)


@app.post("/clubs/{club_id}/billing/portal", response_model=PortalSession)
def club_billing_portal(club_id: str, body: PortalRequest, session: Session = Depends(club_admin)):
    """Short-lived URL of the payment provider's hosted page (payment method, receipts). Redirect the browser there;
    the provider sends the admin back to `returnPath` (a /club/... page)."""
    url, expires = billing.portal_session(store, club_id, body.return_path, session)
    return PortalSession(url=url, expires_at=expires)


@app.get("/clubs/{club_id}/billing/invoices/{invoice_id}.pdf")
def club_invoice_pdf(club_id: str, invoice_id: str, session: Session = Depends(club_admin)):
    name, data = billing.invoice_pdf(store, club_id, invoice_id)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


# Mock of the provider's hosted page (stands in for e.g. Stripe's billing portal in this demo).
@app.get("/billing-provider/session/{token}", response_class=HTMLResponse, include_in_schema=False)
def mock_provider_page(token: str):
    return HTMLResponse(billing.provider_page(store, token), headers={"Cache-Control": "no-store"})


@app.post("/billing-provider/session/{token}/simulate-update", include_in_schema=False)
def mock_provider_update(token: str):
    return RedirectResponse(billing.simulate_update(store, token), status_code=303)


@app.get("/clubs/{club_id}", response_model=ClubProfile)
def club_profile_get(club_id: str, session: Session = Depends(club_admin)):
    """C5: the club profile as admins edit it, the sport options and the sports its teams play."""
    return club_profile.profile(store, club_id)


@app.patch("/clubs/{club_id}", response_model=ClubProfile)
def club_profile_patch(club_id: str, body: ClubPatch, session: Session = Depends(club_admin)):
    """Edit name, short name, logo (`logoUrl` from POST /uploads or null), colours, town, sports, description,
    contact email. 409 `sport_in_use` when removing a sport a team plays; 422 for an image that wasn't uploaded."""
    club_profile.update(store, club_id, body, body.model_fields_set)
    return club_profile.profile(store, club_id)


@app.post("/clubs/{club_id}/sponsors", response_model=Sponsor, status_code=201)
def add_club_sponsor(club_id: str, body: SponsorIn, session: Session = Depends(club_admin)):
    """Add a sponsor: name, link, logo (from POST /uploads), where it shows: `cards`, `club_page`, `reports`."""
    return club_profile.add_sponsor(store, club_id, body)


@app.patch("/clubs/{club_id}/sponsors/{sponsor_id}", response_model=Sponsor)
def update_club_sponsor(club_id: str, sponsor_id: str, body: SponsorPatch, session: Session = Depends(club_admin)):
    return club_profile.update_sponsor(store, club_id, sponsor_id, body, body.model_fields_set)


@app.delete("/clubs/{club_id}/sponsors/{sponsor_id}", status_code=204)
def remove_club_sponsor(club_id: str, sponsor_id: str, session: Session = Depends(club_admin)):
    club_profile.remove_sponsor(club_id, sponsor_id)
    return Response(status_code=204)


@app.post("/uploads", response_model=Upload, status_code=201)
async def upload_image(request: Request, session: Session = Depends(get_session)):
    """Image upload for club admins and publishers: send the file itself as the body with its `Content-Type`
    (PNG, JPEG, WebP or GIF, at most 2 MB). Returns the URL to use as `logoUrl`."""
    if not session.signed_in:
        raise HTTPException(401, "Log in to upload images.")
    if not any(r in ("admin", "publisher") for _, r in session.roles):  # club logos / sponsors, event logos, news images
        raise HTTPException(403, {"code": "not_club_admin", "message": "Only club admins and publishers can upload images."})
    if int(request.headers.get("content-length") or 0) > club_profile.MAX_IMAGE_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "Images can be at most 2 MB."})
    return club_profile.save_upload(store, request.headers.get("content-type", ""), await request.body())


@app.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    item = store.uploads.get(upload_id)
    if item is None:
        raise HTTPException(404, "Image not found")
    ctype, data = item
    return Response(content=data, media_type=ctype, headers={
        "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


@app.get("/clubs/{club_id}/matches", response_model=PortalMatches)
def list_club_matches(club_id: str, session: Session = Depends(club_admin)):
    """C4: the club's upcoming (live, awaiting result, scheduled) and past matches with scorer, data level and
    status, plus the members who can be picked as scorer."""
    return matches_admin.club_matches(store, club_id)


@app.patch("/matches/{match_id}", response_model=PortalMatch | ManagedMatch)
def update_match(match_id: str, body: MatchPatch, session: Session = Depends(get_session)):
    """Admins of either club playing: assign / remove the scorer (`scorerId`, a scorer in your club) and set the data
    level (`live` / `results_only`, until kick-off). 409 `finished` / `started`, 422 `not_a_scorer`.
    The event's publisher (P4): also `startsAt`, `venue` (before kick-off), `score` (enter the result once started, or
    correct a finished one — fans see a correction note) and `scorerId` (one of the event's scorers)."""
    m = store.get_match(match_id)
    hit = m and event_manage.event_of_match(store, m, session)
    if hit:
        return event_manage.update_match(store, session, hit[0], hit[1], m, body, body.model_fields_set)
    m, club_id = matches_admin.match_for_admin(store, match_id, session)
    return matches_admin.update(store, m, club_id, body, body.model_fields_set)


@app.delete("/matches/{match_id}", status_code=204)
def delete_match(match_id: str, session: Session = Depends(get_session)):
    """P4: remove a fixture that hasn't started (the event's publisher)."""
    m = store.get_match(match_id)
    if m is None:
        raise HTTPException(404, "Match not found")
    event_manage.delete_match(store, session, m)
    return Response(status_code=204)


@app.post("/matches/{match_id}/finish", response_model=PortalMatch)
def finish_match(match_id: str, body: FinishMatch, session: Session = Depends(get_session)):
    """Enter the final score `{score: [home, away]}`: a results-only match once it has started, or end a live one.
    Club admins of either team and the assigned scorer (S2). Fans get the result and the AI match report.
    Sending the same final score again is fine (offline retries); 409 `finished` for a different score, `not_started`."""
    m, _ = scoring.match_access(store, match_id, session)
    if m.status == "finished" and m.score == body.score:
        return matches_admin.to_club_match(store, m)
    result = matches_admin.finish(store, m, body.score)
    return result


@app.get("/clubs/{club_id}/members", response_model=ClubMembers)
def list_club_members(club_id: str, session: Session = Depends(club_admin)):
    """C2: the club's members and invites, with the Premium seat count. Search, filters and sorting are done
    in the page (rosters are small). `inviteLink` is only filled in dev mode (no email service yet)."""
    return club_members.members_page(store, club_id, session, DEV_EMAIL)


@app.post("/clubs/{club_id}/invites", response_model=BulkInviteResult)
def invite_club_members(club_id: str, body: BulkInviteIn, session: Session = Depends(club_admin)):
    """C2 bulk invite. Each row is checked (email, duplicate in the club or the list, role, free seat).
    `dryRun: true` only reports the rows (preview). Otherwise all rows are invited, or none:
    409 `invalid_rows` (duplicate email / no seat) or 422 `invalid_rows`, with every row and its error."""
    return club_members.bulk_invite(store, club_id, body.rows, session, dry_run=body.dry_run, dev=DEV_EMAIL)


@app.patch("/clubs/{club_id}/members/{member_id}", response_model=MemberChange)
def update_club_member(club_id: str, member_id: str, body: MemberPatch, session: Session = Depends(club_admin)):
    """Grant / remove Premium or change the role. 409 `seat_limit` when no seat is free, 409 `self` when you'd
    drop your own admin role. An active member's account follows the change."""
    row = club_members.get_row(store, club_id, member_id)
    club_members.update(store, club_id, row, session, body.premium, body.role)
    return MemberChange(member=club_members.to_model(store, row, session, DEV_EMAIL), seats=club_members.seats(store, club_id))


@app.post("/clubs/{club_id}/members/{member_id}/resend", response_model=MemberChange)
def resend_club_invite(club_id: str, member_id: str, session: Session = Depends(club_admin)):
    """Send a fresh invite link (valid 14 days) to an invited or expired member. 409 `already_active`."""
    row = club_members.get_row(store, club_id, member_id)
    club_members.resend(store, club_id, row, session)
    return MemberChange(member=club_members.to_model(store, row, session, DEV_EMAIL), seats=club_members.seats(store, club_id))


@app.delete("/clubs/{club_id}/members/{member_id}", response_model=MemberChange)
def remove_club_member(club_id: str, member_id: str, session: Session = Depends(club_admin)):
    """Remove a member or cancel an invite; frees their seat and takes away Premium / roles from the club.
    409 `self` for your own row."""
    row = club_members.get_row(store, club_id, member_id)
    club_members.remove(store, club_id, row, session)
    return MemberChange(member=None, seats=club_members.seats(store, club_id))


# ---- Story page (F7) ---------------------------------------------------------

# ---- Events / tournaments (F5) ---------------------------------------------

# ---- Match page (F6) ---------------------------------------------------------

# ---- Explore & search (F2) -------------------------------------------------

