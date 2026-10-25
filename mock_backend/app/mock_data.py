"""Seed data for the fan app (Oulu-area local sport). Replace with a database later."""

from datetime import datetime, timedelta

from .models import AgeGroup, Club, ClubEvent, Comment, Match, Player, Post, PostMedia, PostResult, Region, Sponsor, Sport, Story, Team

SPORTS: list[Sport] = [
    Sport(id="all", label="All"),
    Sport(id="football", label="Football", icon="⚽"),
    Sport(id="ice-hockey", label="Ice hockey", icon="🏒"),
    Sport(id="floorball", label="Floorball", icon="🥍"),
    Sport(id="basketball", label="Basketball", icon="🏀"),
    Sport(id="volleyball", label="Volleyball", icon="🏐"),
    Sport(id="cricket", label="Cricket", icon="🏏"),
]

REGIONS: list[Region] = [
    Region(id="north-ostrobothnia", label="Northern Ostrobothnia"),
    Region(id="lapland", label="Lapland"),
    Region(id="kainuu", label="Kainuu"),
]

AGE_GROUPS: list[AgeGroup] = [
    AgeGroup(id="senior", label="Senior"),
    AgeGroup(id="u20", label="U20"),
    AgeGroup(id="u17", label="U17"),
]

# name -> (lat, lon, region id)
VENUES: dict[str, tuple[float, float, str]] = {
    "Raatti Stadium": (65.0060, 25.4810, "north-ostrobothnia"),
    "Kalevan Kiekkohalli": (65.0130, 25.4900, "north-ostrobothnia"),
    "Ouluhalli": (65.0110, 25.4950, "north-ostrobothnia"),
    "Tervatoppila Arena": (65.0270, 25.5040, "north-ostrobothnia"),
    "Haukiputaan liikuntahalli": (65.1770, 25.3540, "north-ostrobothnia"),
    "Heinäpää artificial turf": (65.0040, 25.4900, "north-ostrobothnia"),
    "Raksila Arena": (65.0108, 25.4954, "north-ostrobothnia"),
    "Raahe Areena": (64.6838, 24.4790, "north-ostrobothnia"),
    "Lappi Areena": (66.5097, 25.7480, "lapland"),
    "Tornion palloiluhalli": (65.8481, 24.1466, "lapland"),
    "Sauvosaari": (65.7365, 24.5637, "lapland"),
    "Kajaanin liikuntahalli": (64.2270, 27.7280, "kainuu"),
    "Kuivasjärvi cricket ground": (65.0590, 25.4720, "north-ostrobothnia"),
}

# id, name, short, color, city, region, home venue
_CLUBS = [
    ("tarmo", "Oulun Tarmo", "TAR", "#e4572e", "Oulu", "north-ostrobothnia", "Raatti Stadium"),
    ("kemicity", "Kemi City FC", "KEM", "#2e86ab", "Kemi", "lapland", "Sauvosaari"),
    ("ols", "OLS", "OLS", "#3bb273", "Oulu", "north-ostrobothnia", "Heinäpää artificial turf"),
    ("acoulu", "AC Oulu", "ACO", "#3a4250", "Oulu", "north-ostrobothnia", "Raatti Stadium"),
    ("kiekkooulu", "Kiekko-Oulu", "KKO", "#e0a100", "Oulu", "north-ostrobothnia", "Kalevan Kiekkohalli"),
    ("roki", "RoKi", "ROK", "#7768ae", "Rovaniemi", "lapland", "Lappi Areena"),
    ("karpat", "Oulun Kärpät", "KÄR", "#1d1d1d", "Oulu", "north-ostrobothnia", "Raksila Arena"),
    ("hokki", "Kajaanin Hokki", "HOK", "#0f7173", "Kajaani", "kainuu", "Kajaanin liikuntahalli"),
    ("tornio", "Tornio Bats", "TOB", "#d7263d", "Tornio", "lapland", "Tornion palloiluhalli"),
    ("hoops", "Oulu Hoops", "OHO", "#f46036", "Oulu", "north-ostrobothnia", "Tervatoppila Arena"),
    ("raahe", "Raahe Rays", "RAR", "#1b998b", "Raahe", "north-ostrobothnia", "Raahe Areena"),
    ("hvb", "Haukiputaan Volley", "HVB", "#c5283d", "Haukipudas", "north-ostrobothnia", "Haukiputaan liikuntahalli"),
    ("ksp", "Kajaani Spike", "KSP", "#255f85", "Kajaani", "kainuu", "Kajaanin liikuntahalli"),
    # cricket (fictional clubs)
    ("occ", "Oulu Cricket Club", "OCC", "#2b9348", "Oulu", "north-ostrobothnia", "Kuivasjärvi cricket ground"),
    ("kemistrikers", "Kemi Strikers", "KST", "#e76f51", "Kemi", "lapland", "Kuivasjärvi cricket ground"),
    ("raaheroyals", "Raahe Royals", "RRY", "#6d597a", "Raahe", "north-ostrobothnia", "Kuivasjärvi cricket ground"),
    ("rovcc", "Rovaniemi CC", "RCC", "#264653", "Rovaniemi", "lapland", "Kuivasjärvi cricket ground"),
]

# id, name, short, color, sport, league, club id, age group
_TEAMS = [
    ("tarmo", "Oulun Tarmo", "TAR", "#e4572e", "football", "Kakkonen", "tarmo", "senior"),
    ("kemi", "Kemi City", "KEM", "#2e86ab", "football", "Kakkonen", "kemicity", "senior"),
    ("olsu17", "OLS U17", "OLS", "#3bb273", "football", "Juniors U17", "ols", "u17"),
    ("acou17", "AC Oulu U17", "ACO", "#3a4250", "football", "Juniors U17", "acoulu", "u17"),
    ("kko", "Kiekko-Oulu", "KKO", "#e0a100", "ice-hockey", "Suomi-sarja", "kiekkooulu", "senior"),
    ("roki", "RoKi Juniors", "ROK", "#7768ae", "ice-hockey", "Suomi-sarja", "roki", "senior"),
    ("karpat", "Kärpät U20", "KÄR", "#1d1d1d", "ice-hockey", "U20 SM-sarja", "karpat", "u20"),
    ("hokki", "Hokki U20", "HOK", "#0f7173", "ice-hockey", "U20 SM-sarja", "hokki", "u20"),
    ("olsfb", "OLS Salibandy", "OLS", "#3bb273", "floorball", "Division 1 · North", "ols", "senior"),
    ("tornio", "Tornio Bats", "TOB", "#d7263d", "floorball", "Division 1 · North", "tornio", "senior"),
    ("hoops", "Oulu Hoops", "OHO", "#f46036", "basketball", "Division 2", "hoops", "senior"),
    ("raahe", "Raahe Rays", "RAR", "#1b998b", "basketball", "Division 2", "raahe", "senior"),
    ("hvb", "Haukipudas VB", "HVB", "#c5283d", "volleyball", "Women · Div 1", "hvb", "senior"),
    ("ksp", "Kajaani Spike", "KSP", "#255f85", "volleyball", "Women · Div 1", "ksp", "senior"),
    # Northern Junior Cup U17 entrants
    ("tarmou17", "Tarmo U17", "TAR", "#e4572e", "football", "Juniors U17", "tarmo", "u17"),
    ("kemiu17", "Kemi City U17", "KEM", "#2e86ab", "football", "Juniors U17", "kemicity", "u17"),
    ("hvbu17", "Haukipudas U17", "HAU", "#c5283d", "football", "Juniors U17", "hvb", "u17"),
    ("raaheu17", "Raahe U17", "RAA", "#1b998b", "football", "Juniors U17", "raahe", "u17"),
    ("kspu17", "Kajaani U17", "KAJ", "#255f85", "football", "Juniors U17", "ksp", "u17"),
    ("torniou17", "Tornio U17", "TOR", "#d7263d", "football", "Juniors U17", "tornio", "u17"),
    # cricket
    ("occ", "Oulu CC", "OCC", "#2b9348", "cricket", "Oulu Sixes", "occ", "senior"),
    ("kst", "Kemi Strikers", "KST", "#e76f51", "cricket", "Oulu Sixes", "kemistrikers", "senior"),
    ("rry", "Raahe Royals", "RRY", "#6d597a", "cricket", "Oulu Sixes", "raaheroyals", "senior"),
    ("rcc", "Rovaniemi CC", "RCC", "#264653", "cricket", "Oulu Sixes", "rovcc", "senior"),
]

_CLUB_REGION = {c[0]: c[5] for c in _CLUBS}

TEAMS: dict[str, Team] = {
    t[0]: Team(id=t[0], name=t[1], short=t[2], color=t[3], sport=t[4], league=t[5],
               club_id=t[6], region=_CLUB_REGION[t[6]], age_group=t[7])
    for t in _TEAMS
}

# Fictional local businesses used for the club sponsor strips.
_SPONSORS = [
    "Lumiranta Bakery", "Koivuniemi Auto", "Tervaleppä Café", "Pikkuhauki Sport",
    "Kallioranta Electric", "Hilla Dental", "Revontuli Print", "Saarela Timber",
    "Jokisuu Optics", "Lakeus Insurance Agency", "Merikoski Plumbing", "Tähtikoski Hotel",
]


def _sponsors_for(index: int) -> list[Sponsor]:
    return [Sponsor(id=f"sp-{index}-{k}", name=_SPONSORS[(index * 5 + k * 3) % len(_SPONSORS)]) for k in range(3 + index % 2)]


CLUBS: dict[str, Club] = {}
for _i, (_id, _name, _short, _color, _city, _region, _venue) in enumerate(_CLUBS):
    _teams = [t for t in TEAMS.values() if t.club_id == _id]
    _lat, _lon, _ = VENUES[_venue]
    CLUBS[_id] = Club(
        id=_id, name=_name, short=_short, color=_color, city=_city, region=_region,
        sports=sorted({t.sport for t in _teams}), team_ids=[t.id for t in _teams],
        venue=_venue, lat=_lat, lon=_lon, sponsors=_sponsors_for(_i),
        contact_email=f"info@{_id}.example.org",  # mock club contact
    )

# Fictional players. id, name, number, position, team id
_PLAYERS = [
    ("pl1", "Eetu Mäkelä", 9, "Forward", "tarmo"),
    ("pl2", "Joonas Heikkinen", 1, "Goalkeeper", "tarmo"),
    ("pl3", "Aleksi Nieminen", 10, "Midfielder", "kemi"),
    ("pl4", "Veeti Laine", 7, "Winger", "olsu17"),
    ("pl5", "Onni Korhonen", 14, "Defender", "acou17"),
    ("pl6", "Lauri Virtanen", 23, "Centre", "kko"),
    ("pl7", "Niko Salo", 31, "Goaltender", "kko"),
    ("pl8", "Elias Kallio", 19, "Winger", "roki"),
    ("pl9", "Aaro Hämäläinen", 91, "Centre", "karpat"),
    ("pl10", "Topias Rantanen", 4, "Defence", "hokki"),
    ("pl11", "Miro Koskinen", 12, "Forward", "olsfb"),
    ("pl12", "Sami Lehtonen", 8, "Defender", "tornio"),
    ("pl13", "Kalle Peltonen", 5, "Point guard", "hoops"),
    ("pl14", "Jere Turunen", 11, "Forward", "raahe"),
    ("pl15", "Emma Laaksonen", 6, "Setter", "hvb"),
    ("pl16", "Iida Mattila", 9, "Outside hitter", "hvb"),
    ("pl17", "Aino Saarinen", 2, "Libero", "ksp"),
]

PLAYERS: list[Player] = [
    Player(id=p[0], name=p[1], number=p[2], position=p[3], team=TEAMS[p[4]]) for p in _PLAYERS
]

MIN = 60_000


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def seed(now_ms: int) -> tuple[list[Match], list[Post]]:
    """Build matches and posts relative to ``now_ms`` (epoch milliseconds)."""
    today = datetime.fromtimestamp(now_ms / 1000).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    def at(day: int, h: int, m: int = 0) -> int:
        return _ms(today + timedelta(days=day, hours=h, minutes=m))

    T = TEAMS
    matches = [
        # live
        Match(id="m1", sport="football", league="Kakkonen · Group C", status="live", clock=63, period="2nd half",
              home=T["tarmo"], away=T["kemi"], score=[2, 1], venue="Raatti Stadium", viewers=412,
              last_event="⚽ 58′ Tarmo retake the lead with a strike from the edge of the box."),
        Match(id="m2", sport="ice-hockey", league="Suomi-sarja", status="live", clock=34, period="2nd period",
              home=T["kko"], away=T["roki"], score=[0, 0], venue="Kalevan Kiekkohalli", viewers=238,
              last_event="🧤 31′ Big save on a RoKi breakaway keeps it scoreless."),
        Match(id="m3", sport="floorball", league="Division 1 · North", status="live", clock=49, period="3rd period",
              home=T["olsfb"], away=T["tornio"], score=[5, 5], venue="Ouluhalli", viewers=97,
              last_event="🥍 47′ Tornio equalise again — 5–5 with 13 minutes left."),
        # upcoming
        Match(id="m4", sport="basketball", league="Division 2", status="upcoming", starts_at=now_ms + 25 * MIN,
              home=T["hoops"], away=T["raahe"], venue="Tervatoppila Arena"),
        Match(id="m5", sport="volleyball", league="Women · Div 1", status="upcoming", starts_at=now_ms + 80 * MIN,
              home=T["hvb"], away=T["ksp"], venue="Haukiputaan liikuntahalli"),
        Match(id="m6", sport="football", league="Juniors U17", status="upcoming", starts_at=at(1, 12),
              home=T["olsu17"], away=T["acou17"], venue="Heinäpää artificial turf"),
        Match(id="m7", sport="ice-hockey", league="Suomi-sarja", status="upcoming", starts_at=at(1, 18, 30),
              home=T["roki"], away=T["kko"], venue="Lappi Areena"),
        Match(id="m8", sport="floorball", league="Division 1 · North", status="upcoming", starts_at=at(1, 19),
              home=T["tornio"], away=T["olsfb"], venue="Tornion palloiluhalli"),
        Match(id="m9", sport="football", league="Kakkonen · Group C", status="upcoming", starts_at=at(2, 14),
              home=T["kemi"], away=T["tarmo"], venue="Sauvosaari"),
        Match(id="m10", sport="football", league="Juniors U17", status="upcoming", starts_at=at(4, 17, 30),
              home=T["tarmou17"], away=T["kemiu17"], venue="Raatti Stadium"),
        # junior friendly played earlier today, results only: waits for the club to enter the result (C4)
        Match(id="m11", sport="football", league="Juniors U17 · Friendly", status="upcoming", starts_at=now_ms - 150 * MIN,
              home=T["olsu17"], away=T["tarmou17"], venue="Heinäpää artificial turf"),
        # finished
        Match(id="r1", sport="ice-hockey", league="U20 SM-sarja", status="finished", ended_at=now_ms - 95 * MIN,
              home=T["karpat"], away=T["hokki"], score=[4, 2], venue="Raksila Arena"),
        Match(id="r2", sport="basketball", league="Division 2", status="finished", ended_at=at(-1, 20, 30),
              home=T["raahe"], away=T["hoops"], score=[71, 78], venue="Raahe Areena"),
        Match(id="r3", sport="volleyball", league="Women · Div 1", status="finished", ended_at=at(-1, 19, 45),
              home=T["ksp"], away=T["hvb"], score=[1, 3], venue="Kajaanin liikuntahalli"),
        Match(id="r4", sport="football", league="Kakkonen · Group C", status="finished", ended_at=at(-7, 16),
              home=T["kemi"], away=T["tarmo"], score=[0, 1], venue="Sauvosaari"),
        Match(id="r5", sport="football", league="Kakkonen · Group C", status="finished", ended_at=at(-14, 16),
              home=T["tarmo"], away=T["kemi"], score=[2, 2], venue="Raatti Stadium"),
        Match(id="r6", sport="football", league="Juniors U17", status="finished", ended_at=at(-3, 13, 45),
              home=T["olsu17"], away=T["acou17"], score=[4, 1], venue="Heinäpää artificial turf"),
        Match(id="r7", sport="ice-hockey", league="Suomi-sarja", status="finished", ended_at=at(-4, 21),
              home=T["kko"], away=T["roki"], score=[3, 2], venue="Kalevan Kiekkohalli"),
        Match(id="r8", sport="floorball", league="Division 1 · North", status="finished", ended_at=at(-6, 21),
              home=T["olsfb"], away=T["tornio"], score=[7, 4], venue="Ouluhalli"),
        Match(id="r9", sport="ice-hockey", league="U20 SM-sarja", status="finished", ended_at=at(-5, 19, 30),
              home=T["hokki"], away=T["karpat"], score=[1, 3], venue="Kajaanin liikuntahalli"),
        Match(id="r10", sport="basketball", league="Division 2", status="finished", ended_at=at(-8, 20),
              home=T["hoops"], away=T["raahe"], score=[82, 75], venue="Tervatoppila Arena"),
        Match(id="r11", sport="volleyball", league="Women · Div 1", status="finished", ended_at=at(-9, 20),
              home=T["hvb"], away=T["ksp"], score=[3, 0], venue="Haukiputaan liikuntahalli"),
    ]

    posts = [
        Post(id="p1", match_id="m1", type="highlight", sport="football", team_ids=["tarmo", "kemi"], author="Oulun Tarmo",
             created_at=now_ms - 4 * MIN,
             text="What a strike from the edge of the box! Tarmo back in front 2–1 💥",
             media=PostMedia(duration="0:24"), likes=128,
             comments=[
                 Comment(id="c1", author="Aino K.", text="Top corner, unstoppable 🔥", created_at=now_ms - 3 * MIN),
                 Comment(id="c2", author="Mikko", text="Hold on for 30 more minutes, lads!", created_at=now_ms - 2 * MIN),
             ]),
        Post(id="p2", match_id="m3", type="update", sport="floorball", team_ids=["olsfb", "tornio"], author="OurSport Live",
             created_at=now_ms - 9 * MIN,
             text="Five-all heading into the final period at Ouluhalli. This one is going down to the wire.",
             likes=42,
             comments=[Comment(id="c3", author="Jussi", text="Best game of the season so far.", created_at=now_ms - 7 * MIN)]),
        Post(id="p3", match_id="r1", type="result", sport="ice-hockey", team_ids=["karpat", "hokki"], author="OurSport Live",
             created_at=now_ms - 95 * MIN,
             text="Full time: Kärpät U20 4–2 Hokki U20. Two late power-play goals sealed it.",
             result=PostResult(home="Kärpät U20", away="Hokki U20", score=[4, 2]), likes=87),
        Post(id="p4", type="highlight", sport="basketball", team_ids=["hoops"], author="Oulu Hoops",
             created_at=now_ms - 180 * MIN,
             text="Warm-up dunk contest before tonight’s game 🏀 Doors open 30 min before tip-off.",
             media=PostMedia(duration="0:41"), likes=203,
             comments=[Comment(id="c4", author="Sanna", text="See you there!", created_at=now_ms - 150 * MIN)]),
        Post(id="p5", type="update", sport="ice-hockey", team_ids=["kko"], author="Kiekko-Oulu",
             created_at=now_ms - 300 * MIN,
             text="Lineup news: our captain is back from injury and starts tonight against RoKi.", likes=64),
    ]
    return matches, posts


# ---- Club page content (F3) ------------------------------------------------

DEMO_USER_NAME = "Demo fan"
DEMO_PREMIUM_CLUB = "tarmo"  # the demo account's Premium comes bundled with this club
DEMO_EMAIL = "demo.fan@example.com"
DEMO_ADMIN_CLUBS = ["tarmo", "ols"]  # the Premium demo account runs the club portal for these
DEMO_FAMILY = ["pl4"]  # the Premium demo account is guardian of Veeti Laine (OLS U17)

# Mock invite codes clubs hand out: code -> club whose membership includes Premium.
INVITE_CODES = {"OLS-FAMILY-2026": "ols", "KARPAT-U20": "karpat", "HOOPS-SEASON": "hoops", "TARMO-2026": "tarmo"}
DEFAULT_FOLLOWS = {"clubs": [], "teams": []}  # visitors (guests) follow nothing
DEMO_FOLLOWS = {"clubs": [], "teams": ["tarmo", "kko"]}  # seeded when the demo account signs in


def seed_club_content(now_ms: int) -> tuple[list[ClubEvent], list[Story]]:
    """Club events (non-match) and news stories, relative to ``now_ms``."""
    today = datetime.fromtimestamp(now_ms / 1000).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    def at(day: int, h: int, m: int = 0) -> int:
        return _ms(today + timedelta(days=day, hours=h, minutes=m))

    events = [
        ClubEvent(id="e1", club_id="tarmo", title="Season-ticket night & meet the players", starts_at=at(2, 18),
                  venue="Raatti Stadium", description="Pick up 2027 season tickets, get autographs and try the new kit."),
        ClubEvent(id="e2", club_id="tarmo", title="Kids’ football camp (ages 7–12)", starts_at=at(6, 10),
                  venue="Heinäpää artificial turf", description="Three hours of games and drills with Tarmo coaches."),
        ClubEvent(id="e3", club_id="tarmo", title="Volunteer briefing for home games", starts_at=at(9, 17, 30),
                  venue="Raatti Stadium clubhouse"),
        ClubEvent(id="e4", club_id="ols", title="Junior floorball try-outs", starts_at=at(1, 17),
                  venue="Ouluhalli", description="Open to players born 2010–2014. Bring indoor shoes."),
        ClubEvent(id="e5", club_id="kiekkooulu", title="Open skate with the team", starts_at=at(3, 18),
                  venue="Kalevan Kiekkohalli"),
        ClubEvent(id="e6", club_id="karpat", title="U20 fan evening", starts_at=at(4, 18), venue="Raksila Arena"),
        ClubEvent(id="e7", club_id="hoops", title="3×3 street tournament", starts_at=at(5, 12),
                  venue="Tervatoppila Arena"),
        ClubEvent(id="e8", club_id="hvb", title="Volleyball school open day", starts_at=at(2, 16),
                  venue="Haukiputaan liikuntahalli"),
    ]

    stories = [
        Story(id="s1", club_id="tarmo", tag="Match report", author="Tarmo media", published_at=at(-7, 18),
              title="Late winner at Sauvosaari keeps Tarmo top",
              summary="A header in the 88th minute settled a tight derby away in Kemi.",
              body=["Oulun Tarmo left it late again, winning 1–0 at Sauvosaari thanks to a back-post header two minutes from time.",
                    "Kemi City had the better of the first half, but Tarmo’s back line held firm and the travelling fans were rewarded at the end.",
                    "The result keeps Tarmo top of Group C going into the final weeks of the season."]),
        Story(id="s2", club_id="tarmo", tag="Club news", author="Tarmo media", published_at=at(-4, 9),
              title="New floodlights switched on at Raatti",
              summary="Evening games and training get brighter thanks to a new LED system.",
              body=["The new LED floodlights at Raatti Stadium were switched on this week.",
                    "They use about half the energy of the old lamps and meet the lighting standard for televised matches."]),
        Story(id="s3", club_id="tarmo", tag="Interview", author="Tarmo media", published_at=at(-10, 12),
              title="Ten years on the touchline: meet our head coach",
              summary="From the junior pitches to the first team — a decade of Tarmo football.",
              body=["Our head coach joined Tarmo as a junior coach ten years ago.",
                    "We sat down to talk about the club’s young players, the long northern winters and the dream of promotion."]),
        Story(id="s4", club_id="ols", tag="Match report", author="OLS", published_at=at(-3, 15),
              title="OLS U17 into the cup quarter-finals",
              summary="A 4–1 win over AC Oulu U17 at Heinäpää.",
              body=["Two goals in each half sent OLS U17 into the quarter-finals.", "Next up: an away trip in November."]),
        Story(id="s5", club_id="ols", tag="Club news", author="OLS", published_at=at(-5, 10),
              title="Floorball team signs two new defenders",
              summary="Experience added to the back line for the run-in.",
              body=["OLS Salibandy have added two defenders with Division 1 experience to the squad."]),
        Story(id="s6", club_id="kiekkooulu", tag="Club news", author="Kiekko-Oulu", published_at=at(0, 9),
              title="Captain back from injury",
              summary="Our captain returns to the line-up tonight against RoKi.",
              body=["After six weeks out, the captain has been cleared to play and starts tonight."]),
        Story(id="s7", club_id="karpat", tag="Match report", author="Oulun Kärpät", published_at=at(-5, 21),
              title="U20s extend winning run to five",
              summary="A 3–1 win in Kajaani keeps the streak going.",
              body=["Kärpät U20 won 3–1 away at Hokki for a fifth straight win."]),
    ]
    with_story = {s.club_id for s in stories}
    for i, club in enumerate(c for c in CLUBS.values() if c.id not in with_story):
        stories.append(Story(
            id=f"s-pre-{club.id}", club_id=club.id, tag="Club news", author=club.name, published_at=at(-12 - i, 12),
            title=f"{club.name}: season preview",
            summary=f"What to expect from {club.name} this season.",
            body=[f"{club.name} are ready for the new season in {club.city}. Here’s what to look forward to."],
        ))
    return events, stories


def is_junior(team: Team) -> bool:
    """Junior protection: any non-senior age group (U20, U17, …) may include minors.
    No individual player data (rankings, players to watch, player of the match, player search) for them."""
    return team.age_group != "senior"


# ---- Club invites (F13) -----------------------------------------------------------------
# Demo links (real invites use random tokens): /invite/<token>
ROLE_LABELS = {
    "admin": ("Club admin", "Manage the club in the club portal: members, teams, matches, profile and billing."),
    "scorer": ("Scorer", "Enter live scores and match events for the club’s games."),
    "editor": ("News editor", "Write and publish club news, and review AI-written stories before they go out."),
    "coach": ("Coach", "See your team’s full player stats and manage the squad list."),
    "member": ("Club member", "Join the club on OurSport and get its news and match updates."),
    "publisher": ("Publisher", "Create events, confirm their rules and publish news in the publisher portal."),
}
DEMO_INVITES = [
    # token, club, kind, role, invited by, message, expires in days (negative = expired), already used
    ("ols-premium-2026", "ols", "premium_seat", None, "Mari, OLS membership secretary",
     "Your family membership includes OurSport Premium — enjoy the live games!", 14, False),
    ("tarmo-scorer-2026", "tarmo", "role", "scorer", "Jari, Oulun Tarmo team manager",
     "Could you help us score the home games this season?", 7, False),
    ("karpat-premium-expired", "karpat", "premium_seat", None, "Oulun Kärpät office", None, -3, False),
    ("hoops-premium-used", "hoops", "premium_seat", None, "Oulu Hoops", None, 10, True),
]


# ---- Club portal (C-series) ---------------------------------------------------------------
# Mock club subscriptions: Premium seats bought by the club, and followers before the app's own users.
CLUB_SUBSCRIPTIONS = {
    "tarmo": {"plan": "Club", "seats_total": 50, "followers_base": 1240, "price_cents": 300, "since_months": 7,
              "card": ("Visa", "4242", "08/28")},
    "ols": {"plan": "Club Plus", "seats_total": 120, "followers_base": 2315, "price_cents": 250, "since_months": 14,
            "card": ("Mastercard", "5100", "11/27")},
}
DEFAULT_SUBSCRIPTION = {"plan": "Free", "seats_total": 0, "followers_base": 150, "price_cents": 300, "since_months": 0,
                        "card": None}
VAT_RATE = 25.5  # Finnish general VAT rate, %

# Mock member rosters (C2). Generated per club from these numbers; the demo account is added as an admin.
# premium = Premium seats held by generated members (invited + active); expired invites never hold a seat.
CLUB_ROSTERS = {
    "tarmo": {"active": 34, "invited": 5, "expired": 3, "premium": 31, "domain": "tarmo.fi",
              "staff": [("Jari Niemi", "scorer"), ("Pekka Rautio", "scorer"), ("Sanna Heikkilä", "admin")]},
    "ols": {"active": 96, "invited": 6, "expired": 4, "premium": 88, "domain": "ols.fi",
            "staff": [("Aino Korpela", "scorer"), ("Mari Laitinen", "admin")]},
}
FIRST_NAMES = ["Aino", "Eetu", "Elias", "Emma", "Helmi", "Ilona", "Jari", "Juho", "Kalle", "Kerttu", "Lauri", "Leo",
               "Liisa", "Matti", "Minna", "Niko", "Olli", "Onni", "Pauliina", "Riikka", "Sami", "Satu", "Tiina",
               "Tuomas", "Ville", "Aada", "Arttu", "Hanna", "Joni", "Veera"]
LAST_NAMES = ["Hämäläinen", "Heikkinen", "Jokela", "Kangas", "Karjalainen", "Koskinen", "Laine", "Lehtonen",
              "Mäkelä", "Niskanen", "Ojala", "Pesonen", "Rantala", "Salo", "Suominen", "Tervo", "Turunen", "Väisänen",
              "Virtanen", "Ylitalo"]

# Volunteer scorers already assigned to upcoming games (match id -> (club, scorer name in its roster)).
DEMO_SCORERS = {"m1": ("tarmo", "Jari Niemi"), "m9": ("tarmo", "Jari Niemi"), "m6": ("ols", "Aino Korpela"),
                "r4": ("tarmo", "Jari Niemi"), "r5": ("tarmo", "Jari Niemi")}
# Demo editor login (E-series): a sports desk editor who checks AI texts, club news and corrections.
DEMO_EDITOR = {"name": "Antti Leinonen", "email": "antti@northernsportsdesk.example.org", "desk": "Northern Sports Desk"}

# Demo publisher login (P-series): an event organiser who runs two live tournaments and has two in the works.
DEMO_PUBLISHER = {"name": "Kaisa Ranta", "email": "kaisa@oulusportevents.example.org", "organisation": "Oulu Sport Events"}

# Demo scorer login (S1/S2): Oulun Tarmo's volunteer scorer from the club roster.
DEMO_SCORER = {"name": "Jari Niemi", "email": "jari.niemi@tarmo.fi", "club": "tarmo"}
# Games only the result is entered for (no live events): the club enters the final score (C4).
DEMO_RESULTS_ONLY = {"m10", "m11"}

# Fan error reports waiting for the club (story id, message).
DEMO_ERROR_REPORTS = [
    ("report-r4", "The winning goal was scored by #9, not #10."),
    ("s4", "OLS U17 won 4–1, the summary says 4–0 in one place."),
]
