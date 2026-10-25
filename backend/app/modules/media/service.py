"""Media: stream links with the filming check, the filming notice, offline consent
attestations and opt-outs (docs/06-live.md, Live video; docs/13 §4, §7).

OurSport never hosts video: organisers stream with a phone to a provider and attach the
playback URL. Attaching runs the filming check; every failing check is listed in the 409
`filming_not_permitted` answer. An open opt-out pauses live streams of the affected
matches and blocks new ones until the organiser resolves it.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import transaction
from app.core.errors import FieldError, FilmingNotPermitted, NotFound, ValidationFailed
from app.core.live import LiveHub, envelope, match_channel, tournament_channel
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut, TournamentOut
from app.modules.media.models import FilmingAttestation, FilmingNotice, FilmingOptOut, Stream
from app.modules.media.schemas import (
    AttestationIn,
    AttestationOut,
    FilmingNoticeOut,
    OptOutIn,
    OptOutOut,
    StreamIn,
    StreamOut,
)

NOTICE = {
    "en": (
        "{name}: matches may be filmed and streamed live. Junior players are filmed only with "
        "a guardian's consent. To opt out, tell the organiser or use the opt-out form; "
        "privacy notice: /legal/privacy."
    ),
    "fi": (
        "{name}: otteluita voidaan kuvata ja lähettää suorana. Junioripelaajia kuvataan vain "
        "huoltajan suostumuksella. Voit kieltäytyä kertomalla järjestäjälle tai lomakkeella; "
        "tietosuojaseloste: /legal/privacy."
    ),
    "bn": (
        "{name}: ম্যাচগুলো ভিডিও করা ও সরাসরি সম্প্রচার হতে পারে। জুনিয়র খেলোয়াড়দের শুধু "
        "অভিভাবকের সম্মতিতে ভিডিও করা হয়। না চাইলে আয়োজককে জানান বা ফর্ম ব্যবহার করুন; "
        "গোপনীয়তা বিজ্ঞপ্তি: /legal/privacy।"
    ),
}


async def _manager(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> None:
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotFound()


def _stream_out(row: Stream) -> StreamOut:
    return StreamOut(
        id=row.id,
        match_id=row.match_id,
        provider=row.provider,
        playback_url=row.playback_url,
        status=row.status,
        keep_replay=row.keep_replay,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


async def _open_optouts(
    db: AsyncSession, tournament_id: UUID, team_ids: list[UUID]
) -> list[FilmingOptOut]:
    rows = await db.scalars(
        select(FilmingOptOut).where(
            FilmingOptOut.tournament_id == tournament_id,
            FilmingOptOut.team_id.in_(team_ids),
            FilmingOptOut.resolved_at.is_(None),
        )
    )
    return list(rows)


async def filming_check(
    db: AsyncSession, clock: Clock, tournament: TournamentOut, match: MatchOut, data: StreamIn
) -> list[FieldError]:
    """Every reason this match may not be streamed now (empty: it may)."""
    failing: list[FieldError] = []
    policy = tournament.settings.filming_policy
    if policy == "not_allowed":
        failing.append(
            FieldError(field="filming_policy", message="the tournament does not allow filming")
        )
    if not data.rights_confirmed:
        failing.append(
            FieldError(field="rights_confirmed", message="confirm you hold the streaming rights")
        )
    if not data.venue_permission:
        failing.append(
            FieldError(field="venue_permission", message="the venue must allow streaming")
        )
    notice = await db.scalar(
        select(FilmingNotice.id).where(FilmingNotice.tournament_id == tournament.id)
    )
    if notice is None:
        failing.append(
            FieldError(field="filming_notice", message="publish the filming notice first")
        )
    teams = [t for t in (match.home_team_id, match.away_team_id) if t]
    attested = await db.scalar(
        select(FilmingAttestation.id).where(FilmingAttestation.tournament_id == tournament.id)
    )
    if not attested:
        everyone = policy == "consent_required" or tournament.is_junior
        players = await competitions.filming_status(db, clock, tournament.id, teams)
        missing = [p for p in players if (everyone or p.is_junior) and not p.filming_consent]
        if missing:
            failing.append(
                FieldError(
                    field="consents",
                    message=f"{len(missing)} players have no filming consent (or attest "
                    "that consents were collected offline)",
                )
            )
    optouts = await _open_optouts(db, tournament.id, teams)
    if optouts:
        failing.append(
            FieldError(field="optouts", message=f"{len(optouts)} filming opt-outs are open")
        )
    return failing


async def attach_stream(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    match_id: UUID,
    data: StreamIn,
    live: LiveHub | None = None,
) -> StreamOut:
    """Attach a playback link if the filming check passes (organisers)."""
    match = await competitions.get_match(db, match_id)
    await _manager(db, viewer, match.tournament_id)
    tournament = await competitions.get_tournament(db, viewer, match.tournament_id)
    failing = await filming_check(db, clock, tournament, match, data)
    if failing:
        raise FilmingNotPermitted("the filming check did not pass", errors=failing)
    now = clock.now()
    async with transaction(db):
        for old in await db.scalars(
            select(Stream).where(Stream.match_id == match_id, Stream.status != "ended")
        ):
            old.status, old.ended_at = "ended", now
        row = Stream(
            match_id=match_id,
            tournament_id=match.tournament_id,
            provider=data.provider,
            playback_url=str(data.playback_url),
            status="live",
            keep_replay=data.keep_replay,
            consent_check={
                "rights_confirmed": data.rights_confirmed,
                "venue_permission": data.venue_permission,
                "federation_rules_checked": data.federation_rules_checked,
                "policy": tournament.settings.filming_policy,
                "checked_at": now.isoformat(),
            },
            rights_confirmed_by=viewer.user_id,
            started_at=now,
            created_at=now,
        )
        db.add(row)
    await _announce(live, clock, row)
    return _stream_out(row)


async def _announce(live: LiveHub | None, clock: Clock, row: Stream) -> None:
    if live is None:
        return
    data = _stream_out(row).model_dump(mode="json")
    message = envelope("stream", clock.now(), data, match_id=row.match_id)
    await live.publish(match_channel(row.match_id), message)
    await live.publish(tournament_channel(row.tournament_id), message)


async def end_stream(
    db: AsyncSession, clock: Clock, viewer: Viewer, match_id: UUID, live: LiveHub | None = None
) -> None:
    match = await competitions.get_match(db, match_id)
    await _manager(db, viewer, match.tournament_id)
    async with transaction(db):
        rows = list(
            await db.scalars(
                select(Stream).where(Stream.match_id == match_id, Stream.status != "ended")
            )
        )
        for row in rows:
            row.status, row.ended_at = "ended", clock.now()
    for row in rows:
        await _announce(live, clock, row)


async def _can_watch(db: AsyncSession, viewer: Viewer, tournament: TournamentOut) -> bool:
    policy = tournament.settings.live_access
    if policy == "public":
        return True
    if await competitions.manages(db, viewer, tournament.id):
        return True
    return policy == "members" and viewer.is_member


async def match_stream(db: AsyncSession, viewer: Viewer, match_id: UUID) -> StreamOut:
    """The match's live stream (per the live access policy); 404 when there is none."""
    match = await competitions.get_match(db, match_id)
    tournament = await competitions.get_tournament(db, viewer, match.tournament_id)
    row = await db.scalar(
        select(Stream)
        .where(Stream.match_id == match_id, Stream.status == "live")
        .order_by(Stream.created_at.desc())
        .limit(1)
    )
    if row is None or not await _can_watch(db, viewer, tournament):
        raise NotFound()
    return _stream_out(row)


def _notice_out(row: FilmingNotice) -> FilmingNoticeOut:
    return FilmingNoticeOut(
        tournament_id=row.tournament_id,
        version=row.version,
        texts=row.texts,
        published_at=row.created_at,
    )


async def publish_notice(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID
) -> FilmingNoticeOut:
    """Publish (a new version of) the venue filming notice in the tournament languages."""
    await _manager(db, viewer, tournament_id)
    tournament = await competitions.get_tournament(db, viewer, tournament_id)
    previous = await db.scalar(
        select(FilmingNotice.version)
        .where(FilmingNotice.tournament_id == tournament_id)
        .order_by(FilmingNotice.version.desc())
        .limit(1)
    )
    texts = {
        lang: NOTICE[lang].format(name=tournament.name)
        for lang in tournament.settings.languages
        if lang in NOTICE
    }
    async with transaction(db):
        row = FilmingNotice(
            tournament_id=tournament_id,
            texts=texts,
            version=(previous or 0) + 1,
            published_by=viewer.user_id,
            created_at=clock.now(),
        )
        db.add(row)
    return _notice_out(row)


async def notice(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> FilmingNoticeOut:
    """The current filming notice (public, for the venue QR code)."""
    await competitions.get_tournament(db, viewer, tournament_id)
    row = await db.scalar(
        select(FilmingNotice)
        .where(FilmingNotice.tournament_id == tournament_id)
        .order_by(FilmingNotice.version.desc())
        .limit(1)
    )
    if row is None:
        raise NotFound()
    return _notice_out(row)


async def attest(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, data: AttestationIn
) -> AttestationOut:
    """The organiser attests that filming consents were collected offline (stored with
    who and when)."""
    await _manager(db, viewer, tournament_id)
    async with transaction(db):
        row = FilmingAttestation(
            tournament_id=tournament_id,
            statement=data.statement,
            attested_by=viewer.user_id,
            created_at=clock.now(),
        )
        db.add(row)
    return AttestationOut(id=row.id, statement=row.statement, created_at=row.created_at)


def _optout_out(row: FilmingOptOut) -> OptOutOut:
    return OptOutOut(
        id=row.id,
        team_id=row.team_id,
        player_id=row.player_id,
        reason=row.reason,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolution=row.resolution,
    )


async def opt_out(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    data: OptOutIn,
    live: LiveHub | None = None,
) -> OptOutOut:
    """Record an opt-out (organiser, guardian or player 15+). Live streams of the team's
    matches pause at once; new ones are blocked until it is resolved."""
    await competitions.get_tournament(db, viewer, tournament_id)
    if data.player_id is not None:
        team_id = await competitions.player_team(db, tournament_id, data.player_id)
    elif data.team_id is not None:
        team_id = data.team_id
        if team_id not in {e.team_id for e in await competitions.entries_of(db, tournament_id)}:
            raise NotFound()
    else:
        raise ValidationFailed("name the team or the player")
    matches = [
        m.id
        for m in await competitions.list_matches(db, tournament_id)
        if team_id in (m.home_team_id, m.away_team_id)
    ]
    async with transaction(db):
        row = FilmingOptOut(
            tournament_id=tournament_id,
            team_id=team_id,
            player_id=data.player_id,
            requested_by=viewer.user_id,
            reason=data.reason,
            created_at=clock.now(),
        )
        db.add(row)
        paused = list(
            await db.scalars(
                select(Stream).where(Stream.match_id.in_(matches), Stream.status == "live")
            )
        )
        for stream in paused:
            stream.status = "paused"
    for stream in paused:
        await _announce(live, clock, stream)
    return _optout_out(row)


async def optouts(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> list[OptOutOut]:
    await _manager(db, viewer, tournament_id)
    rows = await db.scalars(
        select(FilmingOptOut)
        .where(FilmingOptOut.tournament_id == tournament_id)
        .order_by(FilmingOptOut.created_at)
    )
    return [_optout_out(r) for r in rows]


async def resolve_optout(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    optout_id: UUID,
    resolution: str,
) -> OptOutOut:
    """Resolve an opt-out (e.g. the player will not be filmed, or it was withdrawn)."""
    await _manager(db, viewer, tournament_id)
    async with transaction(db):
        row = await db.get(FilmingOptOut, optout_id)
        if row is None or row.tournament_id != tournament_id:
            raise NotFound()
        row.resolved_at, row.resolution = clock.now(), resolution
    return _optout_out(row)
