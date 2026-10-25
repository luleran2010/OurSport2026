"""Events / tournaments (F5): seed data, standings, qualification scenarios, rules."""

from datetime import datetime, timedelta
from itertools import product

from .mock_data import TEAMS, VENUES, is_junior
from .models import (
    StoryText,
    GroupStandings, Match, Organiser, RuleSection, RulesSummary, ScenarioCard, ScenarioFixture,
    ScenariosResponse, StandingRow, StandingsResponse, Story, Tiebreak, TopScorer, Tournament,
    TournamentGroup,
)

MIN = 60_000
HOUR = 60 * MIN
CRICKET_OVERS = 6  # "sixes": six overs per innings

# (player name, team id, goals) per adult tournament; none of the current demo events qualify.
TOP_SCORERS: dict[str, list[tuple[str, str, int]]] = {}


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def seed_tournaments(now: int) -> tuple[list[Tournament], list[Match], list[Story]]:
    today = datetime.fromtimestamp(now / 1000).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    def day(d: int, h: int = 0, m: int = 0) -> int:
        return _ms(today + timedelta(days=d, hours=h, minutes=m))

    T = TEAMS

    cup = Tournament(
        id="njc-u17", name="Northern Junior Cup U17", sport="football",
        starts_at=day(-1, 9), ends_at=day(1, 18),
        organiser=Organiser(name="OLS", club_id="ols"), venue="Heinäpää artificial turf",
        region="north-ostrobothnia",
        format="Two groups of four. Top two in each group reach the semi-finals.",
        results_only=False, qualify_count=2, qualify_label="the semi-finals",
        points_win=3, points_draw=1, match_minutes=80,
        tiebreak=Tiebreak(key="gd", label="GD", description="Goal difference"),
        for_label="GF", against_label="GA",
        groups=[
            TournamentGroup(id="A", name="Group A", team_ids=["olsu17", "acou17", "tarmou17", "kemiu17"]),
            TournamentGroup(id="B", name="Group B", team_ids=["hvbu17", "raaheu17", "kspu17", "torniou17"]),
        ],
        teams=[T[i] for i in ["olsu17", "acou17", "tarmou17", "kemiu17", "hvbu17", "raaheu17", "kspu17", "torniou17"]],
    )
    sixes = Tournament(
        id="oulu-sixes", name="Oulu Cricket Sixes", sport="cricket",
        starts_at=day(-2, 10), ends_at=day(1, 17),
        organiser=Organiser(name="Oulu Cricket Club", club_id="occ"), venue="Kuivasjärvi cricket ground",
        region="north-ostrobothnia",
        format="Six-over matches, everyone plays everyone once. Top two meet in the final.",
        results_only=True, qualify_count=2, qualify_label="the final",
        points_win=2, points_draw=1, match_minutes=90,
        tiebreak=Tiebreak(key="nrr", label="NRR", description="Net run rate"),
        for_label="Runs", against_label="Conc.",
        groups=[TournamentGroup(id="L", name="League", team_ids=["occ", "kst", "rry", "rcc"])],
        teams=[T[i] for i in ["occ", "kst", "rry", "rcc"]],
    )

    def fx(mid, t, stage, home, away, venue, *, score=None, ended=None, starts=None, live_clock=None):
        base = dict(id=mid, sport=t.sport, league=t.name, home=T[home], away=T[away], venue=venue,
                    tournament_id=t.id, stage=stage)
        if live_clock is not None:
            return Match(**base, status="live", score=score, clock=live_clock,
                         period="2nd half" if live_clock > 40 else "1st half", viewers=40 + live_clock,
                         last_event="Cup game in progress", starts_at=now - live_clock * 4 * MIN)
        if ended is not None:
            return Match(**base, status="finished", score=score, ended_at=ended)
        return Match(**base, status="upcoming", starts_at=starts)

    H, R = "Heinäpää artificial turf", "Raatti Stadium"
    C = "Kuivasjärvi cricket ground"
    matches = [
        # Group A
        fx("njc1", cup, "Group A", "olsu17", "acou17", H, score=[2, 1], ended=now - 26 * HOUR),
        fx("njc2", cup, "Group A", "tarmou17", "kemiu17", R, score=[0, 0], ended=now - 26 * HOUR),
        fx("njc3", cup, "Group A", "olsu17", "tarmou17", H, score=[1, 1], ended=now - 3 * HOUR),
        fx("njc4", cup, "Group A", "acou17", "kemiu17", R, score=[3, 0], ended=now - 3 * HOUR),
        fx("njc5", cup, "Group A", "olsu17", "kemiu17", H, score=[1, 0], live_clock=55),
        fx("njc6", cup, "Group A", "acou17", "tarmou17", R, score=[0, 1], live_clock=30),
        # Group B
        fx("njc7", cup, "Group B", "hvbu17", "raaheu17", H, score=[1, 2], ended=now - 25 * HOUR),
        fx("njc8", cup, "Group B", "kspu17", "torniou17", R, score=[0, 3], ended=now - 25 * HOUR),
        fx("njc9", cup, "Group B", "hvbu17", "kspu17", H, score=[2, 0], ended=now - 2 * HOUR),
        fx("njc10", cup, "Group B", "raaheu17", "torniou17", R, score=[1, 1], ended=now - 2 * HOUR),
        fx("njc11", cup, "Group B", "hvbu17", "torniou17", H, starts=now + 2 * HOUR),
        fx("njc12", cup, "Group B", "raaheu17", "kspu17", R, starts=now + 2 * HOUR),
        # Oulu Sixes (runs)
        fx("ocs1", sixes, "League", "occ", "kst", C, score=[78, 65], ended=day(-2, 12)),
        fx("ocs2", sixes, "League", "rry", "rcc", C, score=[54, 59], ended=day(-2, 14)),
        fx("ocs3", sixes, "League", "occ", "rry", C, score=[71, 72], ended=day(-1, 12)),
        fx("ocs4", sixes, "League", "kst", "rcc", C, score=[88, 61], ended=day(-1, 14)),
        fx("ocs5", sixes, "League", "occ", "rcc", C, starts=day(1, 11)),
        fx("ocs6", sixes, "League", "kst", "rry", C, starts=day(1, 13)),
    ]

    stories = [
        Story(id="ts1", tournament_id=cup.id, tag="Day 1 report", author="Cup media", published_at=now - 24 * HOUR,
              title="OLS and Raahe make winning starts",
              summary="Two narrow wins and a goalless draw on a cold opening day.",
              body=["OLS edged AC Oulu 2–1 at Heinäpää while Raahe came from behind to beat Haukipudas.",
                    "Tornio were the most convincing side of the day, winning 3–0 in Kajaani’s first game."]),
        Story(id="ts2", tournament_id=cup.id, tag="Preview", author="Cup media", published_at=now - 90 * MIN,
              title="Final group round: who needs what",
              summary="Group A is wide open going into the last games.",
              body=["Three teams can still finish top of Group A.",
                    "Check the Scenarios tab for what your team needs — it updates as results come in."],
              team_ids=["olsu17", "acou17", "tarmou17", "kemiu17"], available_languages=["en", "fi"],
              translations={"fi": StoryText(
                  title="Viimeinen lohkokierros: kuka tarvitsee mitä",
                  summary="A-lohko on täysin auki ennen viimeisiä otteluita.",
                  body=["Kolme joukkuetta voi vielä voittaa A-lohkon.",
                        "Katso Skenaariot-välilehdeltä, mitä joukkueesi tarvitsee – tiedot päivittyvät tulosten mukaan."],
              )}),
        Story(id="ts3", tournament_id=sixes.id, tag="Results", author="Oulu Cricket Club", published_at=day(-1, 16),
              title="Strikers’ big win blows the table open",
              summary="Kemi Strikers posted 88 to climb to the top on net run rate.",
              body=["With two rounds played, three teams are level on points.",
                    "Net run rate will likely decide who reaches Sunday’s final."]),
    ]
    for t in (cup, sixes):
        t.junior = any(is_junior(team) for team in t.teams)
    return [cup, sixes], matches, stories


# ---- standings ---------------------------------------------------------------

def _tiebreak(t: Tournament, scored: int, conceded: int, played: int) -> float:
    if t.tiebreak.key == "nrr":
        return (scored - conceded) / (CRICKET_OVERS * played) if played else 0.0
    return float(scored - conceded)


def _fmt_tiebreak(t: Tournament, v: float) -> str:
    if t.tiebreak.key == "nrr":
        return f"{v:+.3f}"
    return f"{int(v):+d}" if v else "0"


def _group_matches(t: Tournament, group: TournamentGroup, matches: list[Match]) -> list[Match]:
    ids = set(group.team_ids)
    return [m for m in matches if m.tournament_id == t.id and m.home.id in ids and m.away.id in ids]


def _table(t: Tournament, group: TournamentGroup, matches: list[Match]) -> list[dict]:
    stats = {tid: dict(team=TEAMS[tid], p=0, w=0, d=0, l=0, f=0, a=0, pts=0, form=[]) for tid in group.team_ids}
    finished = sorted((m for m in matches if m.status == "finished"), key=lambda m: m.ended_at or 0)
    for m in finished:
        for side, tid in enumerate((m.home.id, m.away.id)):
            s = stats[tid]
            mine, theirs = m.score[side], m.score[1 - side]
            s["p"] += 1
            s["f"] += mine
            s["a"] += theirs
            if mine > theirs:
                s["w"] += 1; s["pts"] += t.points_win; s["form"].append("W")  # noqa: E702
            elif mine == theirs:
                s["d"] += 1; s["pts"] += t.points_draw; s["form"].append("D")  # noqa: E702
            else:
                s["l"] += 1; s["form"].append("L")  # noqa: E702
    rows = list(stats.values())
    for r in rows:
        r["tb"] = _tiebreak(t, r["f"], r["a"], r["p"])
    rows.sort(key=lambda r: (-r["pts"], -r["tb"], -r["f"], r["team"].name))
    return rows


def _statuses(t: Tournament, group: TournamentGroup, matches: list[Match]) -> dict[str, dict]:
    """Enumerate every outcome of the remaining games (points only)."""
    table = _table(t, group, matches)
    base = {r["team"].id: r["pts"] for r in table}
    remaining = [m for m in matches if m.status != "finished"]
    q = t.qualify_count
    results = ("H", "D", "A") if t.points_draw else ("H", "A")
    out: dict[str, dict] = {}

    if not remaining:  # group complete: the table (with tiebreaks) decides
        for i, r in enumerate(table):
            out[r["team"].id] = {"status": "through" if i < q else "out", "own": {}}
        return out

    per_team = {tid: {"sure": True, "possible": False, "own": {}} for tid in base}
    for outcome in product(results, repeat=len(remaining)):
        pts = dict(base)
        own_res: dict[str, list[str]] = {tid: [] for tid in base}
        for m, res in zip(remaining, outcome):
            h, a = m.home.id, m.away.id
            if res == "H":
                pts[h] += t.points_win; own_res[h].append("W"); own_res[a].append("L")  # noqa: E702
            elif res == "A":
                pts[a] += t.points_win; own_res[a].append("W"); own_res[h].append("L")  # noqa: E702
            else:
                pts[h] += t.points_draw; pts[a] += t.points_draw  # noqa: E702
                own_res[h].append("D"); own_res[a].append("D")  # noqa: E702
        for tid in base:
            above = sum(1 for o in base if o != tid and pts[o] > pts[tid])
            level_or_above = sum(1 for o in base if o != tid and pts[o] >= pts[tid])
            sure, possible = level_or_above < q, above < q
            st = per_team[tid]
            st["sure"] &= sure
            st["possible"] |= possible
            key = "".join(own_res[tid])
            o = st["own"].setdefault(key, {"sure": True, "possible": False})
            o["sure"] &= sure
            o["possible"] |= possible
    for tid, st in per_team.items():
        status = "through" if st["sure"] else "out" if not st["possible"] else "alive"
        out[tid] = {"status": status, "own": st["own"]}
    return out


def standings(t: Tournament, matches: list[Match], updated_at: int) -> StandingsResponse:
    groups = []
    for g in t.groups:
        gm = _group_matches(t, g, matches)
        statuses = _statuses(t, g, gm)
        rows = [
            StandingRow(
                position=i + 1, team=r["team"], played=r["p"], won=r["w"], drawn=r["d"], lost=r["l"],
                scored=r["f"], conceded=r["a"], tiebreak_value=round(r["tb"], 3),
                tiebreak_display=_fmt_tiebreak(t, r["tb"]), points=r["pts"], form=r["form"][-3:],
                status=statuses[r["team"].id]["status"],
            )
            for i, r in enumerate(_table(t, g, gm))
        ]
        groups.append(GroupStandings(id=g.id, name=g.name, rows=rows))
    # Individual rankings only for adult events with player data (junior protection, results-only events).
    scorers = None
    if not t.results_only and not t.junior:
        scorers = [TopScorer(player_name=n, team=TEAMS[tid], goals=g) for n, tid, g in TOP_SCORERS.get(t.id, [])]
    return StandingsResponse(
        tournament_id=t.id, updated_at=updated_at, tiebreak=t.tiebreak, for_label=t.for_label,
        against_label=t.against_label, qualify_count=t.qualify_count, groups=groups, top_scorers=scorers,
    )


# ---- scenarios -----------------------------------------------------------------

_WORD = {"W": "win", "D": "draw", "L": "defeat"}


def _alive_text(t: Tournament, own: dict[str, dict], n_left: int, tiebreak: str) -> str:
    if n_left == 0:
        return "Their games are done — now it depends on the other results."
    sure = [k for k, v in own.items() if v["sure"]]
    possible = [k for k, v in own.items() if v["possible"]]
    if n_left == 1:
        if "L" in sure:
            return "Already as good as through — even a defeat should be enough."
        if "D" in sure:
            return "A draw is enough to go through."
        if "W" in sure:
            return "A win takes them through."
        if "W" in possible and "D" not in possible:
            return f"Must win — and then other results or {tiebreak} decide."
        if "D" in possible:
            return f"A win would help a lot; a draw leaves them relying on other results or {tiebreak}."
        return f"Need other results to go their way, then {tiebreak}."
    best = "W" * n_left
    if best in sure:
        return f"Winning their last {n_left} games guarantees a place in {t.qualify_label}."
    return f"Still in it, but they need help from other results or {tiebreak}."


def scenarios(t: Tournament, matches: list[Match], updated_at: int) -> ScenariosResponse:
    cards: list[ScenarioCard] = []
    for g in t.groups:
        gm = _group_matches(t, g, matches)
        table = _table(t, g, gm)
        statuses = _statuses(t, g, gm)
        for pos, r in enumerate(table, start=1):
            team = r["team"]
            left = [m for m in gm if m.status != "finished" and team.id in (m.home.id, m.away.id)]
            st = statuses[team.id]["status"]
            if st == "through":
                headline = f"Through to {t.qualify_label}"
            elif st == "out":
                headline = f"Can no longer reach {t.qualify_label}"
            else:
                headline = _alive_text(t, statuses[team.id]["own"], len(left), t.tiebreak.description.lower())
            max_pts = r["pts"] + t.points_win * len(left)
            detail = (
                f"{r['pts']} pts from {r['p']} game{'s' if r['p'] != 1 else ''}"
                + (f", can reach {max_pts}." if left else ".")
                + f" {g.name}: top {t.qualify_count} go through."
            )
            cards.append(ScenarioCard(
                team=team, group_id=g.id, group_name=g.name, position=pos, points=r["pts"], max_points=max_pts,
                status=st, headline=headline, detail=detail,
                remaining=[
                    ScenarioFixture(
                        match_id=m.id, opponent=m.away if m.home.id == team.id else m.home,
                        status=m.status, starts_at=m.starts_at,
                    ) for m in left
                ],
            ))
    return ScenariosResponse(tournament_id=t.id, updated_at=updated_at, qualify_count=t.qualify_count, cards=cards)


# ---- rules -----------------------------------------------------------------------

def rules_summary(t: Tournament) -> RulesSummary:
    if t.sport == "cricket":
        sections = [
            RuleSection(heading="Match length", text=f"Each side bats for {CRICKET_OVERS} overs. The team with more runs wins."),
            RuleSection(heading="Points", text=f"A win is worth {t.points_win} points. A tie or no result gives each team {t.points_draw} point."),
            RuleSection(heading="Net run rate (NRR)", text="If teams are level on points, net run rate decides: the runs a team scores per over minus the runs it concedes per over, across all its games. Higher is better."),
            RuleSection(heading="Who goes through", text=f"Everyone plays everyone once. The top {t.qualify_count} teams meet in {t.qualify_label}."),
        ]
    else:
        sections = [
            RuleSection(heading="Match length", text=f"Games last {t.match_minutes} minutes ({t.match_minutes // 2} each half). Group games can end in a draw."),
            RuleSection(heading="Points", text=f"A win is worth {t.points_win} points and a draw {t.points_draw} point."),
            RuleSection(heading="If teams are level", text="Teams level on points are separated by goal difference, then goals scored, then the result between them."),
            RuleSection(heading="Who goes through", text=f"{t.format} Semi-finals and the final are knockout games: a draw goes straight to penalties."),
            RuleSection(heading="Squads", text="Players must be under 17 on 1 January. Unlimited rolling substitutions are allowed."),
        ]
    return RulesSummary(tournament_id=t.id, title=f"{t.name} — rules in brief", sections=sections)
