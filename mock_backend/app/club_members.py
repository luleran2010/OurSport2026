"""Club portal C2: members and Premium seats.

Each club has a roster of member rows (plain dicts kept in ``store.club_members[club_id]``):
    id, name, email, role (member | scorer | admin), premium, invited_at, activated_at,
    expires_at (of the pending invite), token (invite link), account_email (set when accepted)
A row's status is derived: active once accepted, otherwise invited until the invite expires.
Premium seats are held by premium rows that are not expired (an invited row reserves its seat).

Rows are linked to fan accounts by email, so changing premium or the role of an active member
also changes what that member's account gets (Premium via the club, club roles).
"""

from __future__ import annotations

import random
import re
import secrets
import unicodedata
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import CLUB_ROSTERS, CLUBS, DEMO_EMAIL, DEMO_PREMIUM_CLUB, DEMO_USER_NAME, FIRST_NAMES, LAST_NAMES
from .models import BulkInviteResult, ClubMember, ClubMembers, InviteRowIn, InviteRowResult, RowError, SeatCount

if TYPE_CHECKING:
    from .store import FeedStore, Session

DAY = 24 * 60 * 60 * 1000
INVITE_DAYS = 14
ROLES = ("member", "scorer", "admin")
PORTAL_ROLES = ("scorer", "admin")  # roles that show up on the member's account
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")


# ---- seeding -----------------------------------------------------------------------------

def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().replace(" ", ".")


def seed_rosters(store: FeedStore) -> None:
    """Deterministic mock rosters for the clubs in CLUB_ROSTERS (same people after every restart)."""
    store.club_members = {}
    for club_id, spec in CLUB_ROSTERS.items():
        rng = random.Random(club_id)
        rows: list[dict] = []

        def add(name, email, role, status, premium, ago_days):
            invited = store.now - ago_days * DAY
            row = {"id": f"u-{club_id}-{len(rows) + 1}", "name": name, "email": email, "role": role,
                   "premium": premium, "invited_at": invited, "activated_at": None, "expires_at": None,
                   "token": None, "account_email": None}
            if status == "active":
                row["activated_at"] = invited + rng.randint(0, 3) * DAY + DAY // 3
                row["account_email"] = email
            else:
                row["expires_at"] = invited + INVITE_DAYS * DAY
                _issue_token(store, club_id, row, keep_dates=True)
            rows.append(row)

        add(DEMO_USER_NAME, DEMO_EMAIL, "admin", "active", club_id == DEMO_PREMIUM_CLUB, 120)
        for name, role in spec["staff"]:
            add(name, f"{_ascii(name)}@{spec['domain']}", role, "active", False, rng.randint(60, 300))
        used_names = {r["name"] for r in rows}
        statuses = ["active"] * spec["active"] + ["invited"] * spec["invited"] + ["expired"] * spec["expired"]
        rng.shuffle(statuses)
        premium_left = spec["premium"]
        for status in statuses:
            while (name := f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}") in used_names:
                pass
            used_names.add(name)
            if status == "expired":
                premium, ago = rng.random() < 0.5, rng.randint(INVITE_DAYS + 1, 40)
            else:
                premium = premium_left > 0 and (status == "invited" or rng.random() < 0.95)
                premium_left -= premium
                ago = rng.randint(1, INVITE_DAYS - 1) if status == "invited" else rng.randint(20, 400)
            mail = rng.choice(["gmail.com", "outlook.com", "hotmail.com", "elisanet.fi", "kolumbus.fi"])
            # some invites are sent before the club knows the name
            add(None if status != "active" and rng.random() < 0.4 else name,
                f"{_ascii(name)}{rng.randint(1, 99) if rng.random() < 0.3 else ''}@{mail}", "member", status, premium, ago)
        # top up to the exact seat count if the random draw left some premium unassigned
        for r in rows:
            if premium_left <= 0:
                break
            if not r["premium"] and r["role"] == "member" and status_of(store, r) != "expired":
                r["premium"], premium_left = True, premium_left - 1
        store.club_members[club_id] = rows


def _issue_token(store: FeedStore, club_id: str, row: dict, *, keep_dates: bool = False, invited_by: str | None = None) -> None:
    """(Re)create the invite link for a row: a premium seat and/or a club role, accepted on /invite/{token}."""
    if row["token"]:
        store.invites.pop(row["token"], None)
    if not keep_dates:
        row["invited_at"] = store.now
        row["expires_at"] = store.now + INVITE_DAYS * DAY
    token = f"{club_id}-{secrets.token_urlsafe(9)}"
    row["token"] = token
    store.invites[token] = {
        "club": club_id, "kind": "premium_seat" if row["premium"] else "role", "role": row["role"],
        "invited_by": invited_by or f"{CLUBS[club_id].name} club admin", "message": None,
        "expires_at": row["expires_at"], "used_by": None, "member": row["id"],
    }


# ---- reads -------------------------------------------------------------------------------

def roster(store: FeedStore, club_id: str) -> list[dict]:
    return store.club_members.setdefault(club_id, [])


def status_of(store: FeedStore, row: dict) -> str:
    if row["activated_at"] is not None:
        return "active"
    return "expired" if (row["expires_at"] or 0) < store.now else "invited"


def seats(store: FeedStore, club_id: str) -> SeatCount:
    from .club_portal import subscription  # avoid an import cycle

    used = sum(1 for r in roster(store, club_id) if r["premium"] and status_of(store, r) != "expired")
    return SeatCount(used=used, total=subscription(store, club_id)["seats_total"])


def _is_you(row: dict, session: Session) -> bool:
    return bool(session.email) and session.email.lower() in {row["email"].lower(), (row["account_email"] or "").lower()}


def to_model(store: FeedStore, row: dict, session: Session, dev: bool) -> ClubMember:
    status = status_of(store, row)
    return ClubMember(
        id=row["id"], name=row["name"], email=row["email"], role=row["role"], premium=row["premium"], status=status,
        invited_at=row["invited_at"], activated_at=row["activated_at"],
        expires_at=row["expires_at"] if status != "active" else None, is_you=_is_you(row, session),
        invite_link=f"/invite/{row['token']}" if dev and status == "invited" and row["token"] else None,
    )


def members_page(store: FeedStore, club_id: str, session: Session, dev: bool) -> ClubMembers:
    from .club_portal import subscription

    rows = sorted(roster(store, club_id), key=lambda r: -r["invited_at"])
    return ClubMembers(club=CLUBS[club_id], plan=subscription(store, club_id)["plan"], seats=seats(store, club_id),
                       members=[to_model(store, r, session, dev) for r in rows], updated_at=store.now)


def get_row(store: FeedStore, club_id: str, member_id: str) -> dict:
    row = next((r for r in roster(store, club_id) if r["id"] == member_id), None)
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": "That member isn’t in the club."})
    return row


# ---- linked accounts ---------------------------------------------------------------------

def _accounts(store: FeedStore, row: dict) -> list[Session]:
    """Signed-up profiles that belong to an active row (matched by the email the invite was accepted with)."""
    if row["activated_at"] is None:
        return []
    from .club_portal import _profiles

    emails = {row["email"].lower(), (row["account_email"] or "").lower()} - {""}
    return [p for p in _profiles(store) if p.email and p.email.lower() in emails]


def _sync_account(store: FeedStore, club_id: str, row: dict, *, removed: bool = False) -> None:
    for p in _accounts(store, row):
        has_premium = row["premium"] and not removed
        if has_premium and not (p.premium_club and p.me().premium):
            p.grant_premium(club_id)
        elif not has_premium and p.premium_club == club_id:
            p.premium_club = p.premium_until = None
        p.roles = [(c, r) for c, r in p.roles if not (c == club_id and r in PORTAL_ROLES)]
        if not removed and row["role"] in PORTAL_ROLES:
            p.roles.append((club_id, row["role"]))


def accept(store: FeedStore, inv: dict, session: Session) -> None:
    """Called when someone accepts a roster invite on /invite/{token}: the row becomes active."""
    row = next((r for r in roster(store, inv["club"]) if r["id"] == inv.get("member")), None)
    if row is None:
        return
    row["activated_at"] = store.now
    row["account_email"] = session.email
    row["name"] = row["name"] or (session.name if session.name else None)
    _sync_account(store, inv["club"], row)


# ---- writes ------------------------------------------------------------------------------

def _seat_limit_error() -> HTTPException:
    return HTTPException(409, {"code": "seat_limit",
                               "message": "All Premium seats are in use. Buy more seats or remove Premium from someone first."})


def update(store: FeedStore, club_id: str, row: dict, session: Session, premium: bool | None, role: str | None) -> None:
    if role is not None and role != row["role"] and _is_you(row, session) and row["role"] == "admin":
        raise HTTPException(409, {"code": "self", "message": "You can’t remove your own admin role. Ask another admin."})
    if premium and not row["premium"]:
        s = seats(store, club_id)
        if status_of(store, row) != "expired" and s.used >= s.total:
            raise _seat_limit_error()
    if premium is not None:
        row["premium"] = premium
    if role is not None:
        row["role"] = role
    if row["token"] in store.invites:  # a pending invite offers what the row says now
        store.invites[row["token"]].update(kind="premium_seat" if row["premium"] else "role", role=row["role"])
    _sync_account(store, club_id, row)


def resend(store: FeedStore, club_id: str, row: dict, session: Session) -> None:
    if row["activated_at"] is not None:
        raise HTTPException(409, {"code": "already_active", "message": "This member has already joined."})
    if row["premium"] and status_of(store, row) == "expired":  # an expired invite gets its seat back
        s = seats(store, club_id)
        if s.used >= s.total:
            raise _seat_limit_error()
    _issue_token(store, club_id, row, invited_by=f"{session.name}, {CLUBS[club_id].name}")


def remove(store: FeedStore, club_id: str, row: dict, session: Session) -> None:
    if _is_you(row, session):
        raise HTTPException(409, {"code": "self", "message": "You can’t remove yourself from the club."})
    _sync_account(store, club_id, row, removed=True)
    store.invites.pop(row["token"] or "", None)
    store.club_members[club_id] = [r for r in roster(store, club_id) if r is not row]


def bulk_invite(store: FeedStore, club_id: str, rows: list[InviteRowIn], session: Session, *,
                dry_run: bool, dev: bool) -> BulkInviteResult:
    """Validate every row; a dry run only reports. A real run creates all rows or none (409/422 with the rows)."""
    existing = {r["email"].lower() for r in roster(store, club_id)}
    s = seats(store, club_id)
    free = s.total - s.used
    seen: set[str] = set()
    results: list[InviteRowResult] = []
    for i, row in enumerate(rows):
        email = row.email.strip()
        name = (row.name or "").strip() or None
        role = (row.role or "member").strip().lower()
        err = None
        if not EMAIL_RE.match(email):
            err = RowError(code="email", message="Not a valid email address.")
        elif email.lower() in existing:
            err = RowError(code="duplicate", message="Already a member or invited.")
        elif email.lower() in seen:
            err = RowError(code="duplicate_in_list", message="This email is in the list twice.")
        elif role not in ROLES:
            err = RowError(code="role", message="Role must be member, scorer or admin.")
        elif row.premium and free <= 0:
            err = RowError(code="seat_limit", message="No Premium seat left for this row.")
        if err is None:
            seen.add(email.lower())
            free -= row.premium
        results.append(InviteRowResult(index=i, email=email, name=name, role=role, premium=row.premium, error=err))

    errors = [r for r in results if r.error]
    if dry_run or errors:
        if not dry_run:
            conflict = any(r.error.code in ("duplicate", "seat_limit") for r in errors)
            raise HTTPException(409 if conflict else 422, {
                "code": "invalid_rows", "message": f"{len(errors)} of {len(results)} rows need fixing. Nothing was sent.",
                "rows": [r.model_dump(by_alias=True) for r in results],
            })
        return BulkInviteResult(rows=results, created=[], seats=s)

    created = []
    for r in results:
        new = {"id": f"u-{club_id}-{secrets.token_hex(4)}", "name": r.name, "email": r.email, "role": r.role,
               "premium": r.premium, "invited_at": store.now, "activated_at": None, "expires_at": None,
               "token": None, "account_email": None}
        _issue_token(store, club_id, new, invited_by=f"{session.name}, {CLUBS[club_id].name}")
        roster(store, club_id).append(new)
        created.append(to_model(store, new, session, dev))
    return BulkInviteResult(rows=results, created=created, seats=seats(store, club_id))
