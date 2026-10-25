"""Match page (F6): status-dependent sections, live stakes, timeline insights, reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import tournaments as T
from .mock_data import PLAYERS, is_junior
from .players import featurable
from .models import (
    HeadToHead, LiveAccess, Match, MatchDetail, PlayerNote, Story, StoryFact, StoryText, TableImpact, TimelineEvent,
    Tournament,
)

if TYPE_CHECKING:
    from .store import FeedStore

MIN = 60_000


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def redact(m: Match, premium: bool) -> Match:
    """Live score, clock and events are premium-only on the match page."""
    if m.status != "live" or premium:
        return m
    return m.model_copy(update={"score": None, "clock": None, "period": None, "last_event": None, "flash": None})


def _group_of(t: Tournament, m: Match):
    return next((g for g in t.groups if m.home.id in g.team_ids and m.away.id in g.team_ids), None)


# ---- stories (AI-written from the fact sheet; fi / en / bn) -----------------

AI_AUTHOR = "OurSport AI"
LANGS = ["en", "fi", "bn"]


def _comp(m: Match) -> str:
    return f"{m.league} · {m.stage}" if m.stage else m.league


def _ai_story(m: Match, kind: str, texts: dict[str, StoryText], facts: list[StoryFact], published: int) -> Story:
    en = texts["en"]
    return Story(
        id=f"{kind}-{m.id}", match_id=m.id, team_ids=[m.home.id, m.away.id], tournament_id=m.tournament_id,
        tag="Preview" if kind == "preview" else "Match report", author=AI_AUTHOR, author_type="ai",
        published_at=published, title=en.title, summary=en.summary, body=en.body,
        available_languages=LANGS, translations={k: v for k, v in texts.items() if k != "en"}, facts=facts,
    )


def preview_story(m: Match, now: int, h2h: HeadToHead | None = None) -> Story:
    home, away, comp, venue = m.home.name, m.away.name, _comp(m), m.venue
    texts = {
        "en": StoryText(
            title=f"Preview: {home} v {away}",
            summary=f"{comp} at {venue}. Here’s what to look out for.",
            body=[f"{home} host {away} at {venue} in the {comp}.",
                  "Check “What’s at stake” for what each side needs, and the head-to-head record."],
        ),
        "fi": StoryText(
            title=f"Ennakko: {home} – {away}",
            summary=f"{comp}, {venue}. Näihin kannattaa kiinnittää huomiota.",
            body=[f"{home} kohtaa kotikentällään joukkueen {away} ({venue}, {comp}).",
                  "Katso kohdasta ”Mitä on pelissä”, mitä kumpikin joukkue tarvitsee, sekä keskinäiset ottelut."],
        ),
        "bn": StoryText(
            title=f"প্রিভিউ: {home} বনাম {away}",
            summary=f"{comp}, {venue}। যা খেয়াল রাখবেন।",
            body=[f"{venue}-এ {comp}-এর ম্যাচে {home} মুখোমুখি হবে {away}-এর।",
                  "কোন দলের কী দরকার এবং মুখোমুখি রেকর্ড জানতে “কী নিয়ে লড়াই” অংশটি দেখুন।"],
        ),
    }
    facts = [
        StoryFact(key="competition", value=comp),
        StoryFact(key="venue", value=venue),
        StoryFact(key="kickoff_at", value="", at=m.starts_at),
    ]
    if h2h is not None:
        facts.append(StoryFact(
            key="head_to_head",
            value=f"{m.home.short} {h2h.home_wins} · {h2h.draws} · {h2h.away_wins} {m.away.short} ({h2h.played})",
        ))
    return _ai_story(m, "preview", texts, facts, published=min(now, m.starts_at or now))


def report_story(m: Match, now: int, timeline: list[TimelineEvent] | None = None,
                 impact: list[TableImpact] | None = None) -> Story:
    h, a = m.score or [0, 0]
    home, away, comp, venue = m.home.name, m.away.name, _comp(m), m.venue
    final = f"{home} {h}–{a} {away}"
    if h == a:
        texts = {
            "en": StoryText(title=f"Honours even: {final}", summary=f"{comp} at {venue}.",
                            body=["Neither side could find a winner.", f"Final score: {final}."]),
            "fi": StoryText(title=f"Tasapeli: {final}", summary=f"{comp}, {venue}.",
                            body=["Kumpikaan joukkue ei löytänyt voittomaalia.", f"Lopputulos: {final}."]),
            "bn": StoryText(title=f"ড্র: {final}", summary=f"{comp}, {venue}।",
                            body=["কোনো দলই জয় নিশ্চিত করতে পারেনি।", f"চূড়ান্ত ফলাফল: {final}।"]),
        }
    else:
        win, lose = (m.home, m.away) if h > a else (m.away, m.home)
        at_home = win is m.home
        texts = {
            "en": StoryText(title=f"{win.name} beat {lose.name} {max(h, a)}–{min(h, a)}", summary=f"{comp} at {venue}.",
                            body=[f"{win.name} took the win {'at home' if at_home else 'away from home'}.",
                                  f"Final score: {final}."]),
            "fi": StoryText(title=f"{win.name} vei voiton {max(h, a)}–{min(h, a)}", summary=f"{comp}, {venue}.",
                            body=[f"{win.name} otti voiton {'kotikentällään' if at_home else 'vieraissa'}.",
                                  f"Lopputulos: {final}."]),
            "bn": StoryText(title=f"{win.name}-এর {max(h, a)}–{min(h, a)} ব্যবধানে জয়", summary=f"{comp}, {venue}।",
                            body=[f"{'ঘরের মাঠে' if at_home else 'প্রতিপক্ষের মাঠে'} জয় পেয়েছে {win.name}।",
                                  f"চূড়ান্ত ফলাফল: {final}।"]),
        }
    facts = [
        StoryFact(key="final_score", value=final),
        StoryFact(key="competition", value=comp),
        StoryFact(key="venue", value=venue),
        StoryFact(key="ended_at", value="", at=m.ended_at),
    ]
    teams = {m.home.id: m.home.name, m.away.id: m.away.name}
    for e in timeline or []:
        if e.kind == "goal" and e.team_id in teams:
            facts.append(StoryFact(key="goal", value=f"{e.minute}′ {teams[e.team_id]}"))
    for i in impact or []:
        facts.append(StoryFact(key="table_move", value=f"{i.team.name}: {i.before or '–'} → {i.after} ({i.group_name})"))
    return _ai_story(m, "report", texts, facts, published=m.ended_at or now)


def localized(story: Story, lang: str | None) -> Story:
    """The story with title/summary/body in `lang` when available (else English); translations stripped."""
    text = story.translations.get(lang or "")
    update = {"translations": {}}
    if text is not None:
        update |= {"title": text.title, "summary": text.summary, "body": text.body, "language": lang}
    return story.model_copy(update=update)


# ---- timeline --------------------------------------------------------------

def seed_timeline(m: Match, now: int, next_id) -> list[TimelineEvent]:
    """Plausible events for a game that is already live when the server starts."""
    clock = m.clock or 1
    ev = [TimelineEvent(id=f"tl-{next_id()}", minute=0, kind="kickoff", text=f"Kick-off at {m.venue}.",
                        at=now - clock * MIN)]
    h, a = m.score or [0, 0]
    goals = [(m.home, i) for i in range(h)] + [(m.away, i) for i in range(a)]
    for n, (team, _) in enumerate(goals, start=1):
        minute = max(1, round(clock * n / (len(goals) + 1)))
        ev.append(TimelineEvent(id=f"tl-{next_id()}", minute=minute, kind="goal", team_id=team.id,
                                text=f"Goal! {team.name} score.", at=now - (clock - minute) * MIN))
    ev.sort(key=lambda e: e.minute)
    ev.append(TimelineEvent(id=f"tl-{next_id()}", minute=clock, kind="insight", ai=True, at=now,
                            text=insight_text(m, ev)))
    return ev


def insight_text(m: Match, timeline: list[TimelineEvent]) -> str:
    """Template-based 'AI insight' (mock). Swap for a model-generated line later."""
    h, a = m.score or [0, 0]
    recent = [e for e in timeline if e.kind == "goal" and e.minute >= (m.clock or 0) - 15]
    if len(recent) >= 2:
        return f"{len(recent)} goals in the last 15 minutes — this game has opened up."
    if h == a:
        return "Evenly matched so far. The next goal could decide it."
    lead, trail = (m.home, m.away) if h > a else (m.away, m.home)
    if abs(h - a) >= 2:
        return f"{lead.name} are in control. {trail.name} need a quick goal to get back in it."
    return f"{lead.name} lead by one. {trail.name} have been pushing — expect a tense finish."


# ---- stakes & table impact -------------------------------------------------

_PHRASE = {"through": "would be through", "out": "would be out", "alive": "would still be in contention"}


def live_stakes(store: FeedStore, m: Match) -> str | None:
    if m.status != "live" or m.score is None:
        return None
    h, a = m.score
    t = store.tournaments.get(m.tournament_id or "")
    if t is None:
        if h == a:
            return "If it ends like this, the points are shared."
        win = m.home if h > a else m.away
        return f"If it ends like this, {win.name} take the win."
    group = _group_of(t, m)
    if group is None:
        return None
    # Treat this game as finished at the current score; other games stay open.
    hypothetical = [x.model_copy(update={"status": "finished", "ended_at": store.now}) if x.id == m.id else x
                    for x in T._group_matches(t, group, store.matches)]
    table = T._table(t, group, hypothetical)
    statuses = T._statuses(t, group, hypothetical)
    pos = {r["team"].id: i + 1 for i, r in enumerate(table)}
    parts = [
        f"{team.name} {ordinal(pos[team.id])} in {group.name} ({_PHRASE[statuses[team.id]['status']]})"
        for team in (m.home, m.away)
    ]
    return "If it ends like this: " + "; ".join(parts) + "."


def table_impact(store: FeedStore, m: Match) -> list[TableImpact] | None:
    t = store.tournaments.get(m.tournament_id or "")
    if t is None or m.status != "finished":
        return None
    group = _group_of(t, m)
    gm = T._group_matches(t, group, store.matches)
    done = [x for x in gm if x.status == "finished"]
    before = [x for x in done if (x.ended_at or 0) < (m.ended_at or 0)]
    after = [x for x in done if (x.ended_at or 0) <= (m.ended_at or 0)]

    def positions(ms):
        return {r["team"].id: (i + 1, r["p"]) for i, r in enumerate(T._table(t, group, ms))}

    pb, pa = positions(before), positions(after)
    out = []
    for team in (m.home, m.away):
        b, played_before = pb[team.id]
        a_ = pa[team.id][0]
        before_pos = b if played_before else None
        if before_pos is None:
            text = f"started in {ordinal(a_)} place"
        elif a_ < b:
            text = f"moved up from {ordinal(b)} to {ordinal(a_)}"
        elif a_ > b:
            text = f"dropped from {ordinal(b)} to {ordinal(a_)}"
        else:
            text = f"stayed {ordinal(a_)}"
        out.append(TableImpact(team=team, group_name=group.name, before=before_pos, after=a_, text=text))
    return out


# ---- players ------------------------------------------------------------------

_WATCH_NOTES = ["Top scorer this season", "In form: scored in the last two games", "Key player at the back",
                "The one to watch in midfield"]


def players_to_watch(m: Match) -> list[PlayerNote]:
    out = []
    for team in (m.home, m.away):
        squad = [p for p in PLAYERS if p.team.id == team.id and featurable(p)][:2]
        out += [PlayerNote(player=p, note=_WATCH_NOTES[(len(out)) % len(_WATCH_NOTES)]) for p in squad]
    return out


def player_of_match(m: Match) -> PlayerNote | None:
    h, a = m.score or [0, 0]
    sides = [m.home, m.away] if h >= a else [m.away, m.home]
    for team in sides:
        squad = [p for p in PLAYERS if p.team.id == team.id and featurable(p)]
        if squad:
            p = squad[sum(map(ord, m.id)) % len(squad)]
            return PlayerNote(player=p, note=f"Outstanding for {team.name} in the {h}–{a} {'draw' if h == a else 'result'}.")
    return None


def head_to_head(store: FeedStore, m: Match) -> HeadToHead:
    pair = {m.home.id, m.away.id}
    games = sorted(
        (x for x in store.matches if x.status == "finished" and {x.home.id, x.away.id} == pair),
        key=lambda x: -(x.ended_at or 0),
    )
    hw = d = aw = 0
    for g in games:
        hs, as_ = g.score
        winner = g.home.id if hs > as_ else g.away.id if as_ > hs else None
        if winner is None:
            d += 1
        elif winner == m.home.id:
            hw += 1
        else:
            aw += 1
    return HeadToHead(played=len(games), home_wins=hw, draws=d, away_wins=aw, matches=games[:5])


# ---- assemble ------------------------------------------------------------------

def build_detail(store: FeedStore, m: Match, premium: bool) -> MatchDetail:
    t = store.tournaments.get(m.tournament_id or "")
    junior = is_junior(m.home) or is_junior(m.away)
    no_players = bool(t and t.results_only) or junior  # junior protection
    d = MatchDetail(
        match=redact(m, premium),
        access=LiveAccess(
            live_allowed=premium,
            reason=None if premium else "Live matches are available for premium members. Ask your club for access.",
        ),
        tournament_name=t.name if t else None,
        junior=junior,
        updated_at=store.now,
    )
    if m.status == "upcoming":
        if t:
            sc = T.scenarios(t, store.matches, store.now).cards
            d.stakes = [c for c in sc if c.team.id in (m.home.id, m.away.id)]
        d.players_to_watch = None if no_players else players_to_watch(m)
        d.head_to_head = head_to_head(store, m)
    elif m.status == "live" and premium:
        d.timeline = store.timelines.get(m.id, [])
        d.live_stakes = live_stakes(store, m)
    elif m.status == "finished":
        d.table_impact = table_impact(store, m)
        d.player_of_match = None if no_players else player_of_match(m)
    return d
