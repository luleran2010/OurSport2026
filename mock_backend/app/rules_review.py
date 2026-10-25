"""Publisher P3: rules review. The organiser checks, corrects and confirms the rules the standings engine uses.

The draft is made from what the rulebook reader found (event_setup.extract_rules). For every rule group the page
shows the value, the sentence it came from and edit controls; things the rulebook didn't settle become required
questions; the engine works through example tables and edge-case tests with the current draft, so the organiser
sees the consequences before confirming. Confirming saves a numbered rule version.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import sport_events
from .event_setup import extract_rules, tick_job

if TYPE_CHECKING:
    from .store import FeedStore, Session

TIEBREAKERS = {
    "goal_difference": "Goal difference",
    "goals_scored": "Goals scored",
    "head_to_head": "Head-to-head result",
    "wins": "Number of wins",
    "net_run_rate": "Net run rate",
    "fair_play": "Fair play points",
    "lots": "Drawing lots",
}
_LABEL_TO_KEY = {"goal difference": "goal_difference", "goals scored": "goals_scored", "head-to-head": "head_to_head",
                 "net run rate": "net_run_rate", "fair play": "fair_play", "drawing lots": "lots", "point difference": "goal_difference",
                 "set ratio": "goal_difference", "point ratio": "goals_scored"}
KNOCKOUT = {"none": "No knockout stage", "final": "A final", "semis": "Semi-finals and a final", "quarters": "Quarter-finals, semi-finals and a final"}


def _score_word(sport: str) -> str:
    sp = sport_events.for_sport(sport)
    return {"Goals": "goal", "Runs": "run", "Points": "point"}.get(sp.score_label if sp else "Goals", "goal")


# ---- draft from the extracted rules ------------------------------------------------------

def _from_extracted(e: dict, r: dict | None) -> dict:
    if r is None:  # "enter rules manually": same cards, empty
        return {"format": {"round_robin": None, "knockout": None}, "points": {"win": None, "draw": None, "loss": None},
                "tiebreakers": [], "advancement": {"per_group": None, "best_runners_up": 0},
                "match": {"minutes": None, "extra_time": None, "penalties": None},
                "walkover": {"for": None, "against": None}, "three_way": None}
    tb = [_LABEL_TO_KEY.get(t.lower(), "goal_difference") for t in r.get("tiebreakers", [])]
    text = (e.get("rules_text") or "").lower()
    ko = "semis" if "semi" in text else "final" if "final" in text else "none"
    return {
        "format": {"round_robin": "double" if "twice" in text or "double round" in text else "single", "knockout": ko},
        "points": {"win": r["pointsWin"], "draw": r["pointsDraw"], "loss": r["pointsLoss"]},
        "tiebreakers": list(dict.fromkeys(tb)),
        "advancement": {"per_group": r["qualifyCount"], "best_runners_up": 0},
        "match": {"minutes": r["matchMinutes"], "extra_time": "extra time" in text, "penalties": "penalt" in text},
        "walkover": {"for": None, "against": None},
        "three_way": "mini_league" if "mini" in text or "among the tied" in text else None,
    }


def draft(store: FeedStore, e: dict) -> dict:
    """The working draft (created on first use)."""
    tick_job(store, e)
    if e.get("rules_draft") is None:
        job = e.get("rules_job")
        if job and job["status"] == "done":
            if e.get("rules") is None:
                e["rules"] = extract_rules(e["sport"], e.get("rules_text", ""), len(e.get("teams") or []) or e.get("planned_teams", 8),
                                           len(e.get("groups") or [1]))
            e["rules_draft"] = _from_extracted(e, e["rules"])
            e["rules_answers"] = {}
            e["rules_marks"] = {}
    return e.get("rules_draft")


# ---- source quotes -----------------------------------------------------------------------

QUOTE_WORDS = {
    "format": ["round robin", "everyone plays", "league", "semi-final", "final", "group"],
    "points": ["point"],
    "tiebreakers": ["ranked", "difference", "run rate", "head-to-head", "head to head", "level", "tie"],
    "advancement": ["top ", "go through", "advance", "qualif", "semi-final"],
    "match": ["minute", "overs", "half", "periods", "x "],
    "walkover": ["walkover", "forfeit", "no-show", "fails to appear", "luovutus"],
}


def quote(text: str, group: str) -> dict | None:
    """The first sentence of the rulebook about this rule group, with the matched words to highlight."""
    if not text:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for word in QUOTE_WORDS[group]:
        for snt in sentences:
            i = snt.lower().find(word)
            if i >= 0:
                end = i + len(word)
                while end < len(snt) and snt[end].isalnum():  # highlight the whole word
                    end += 1
                return {"text": snt.strip()[:400], "start": i, "end": end}
    return None


# ---- the standings engine ----------------------------------------------------------------

def _rows(teams: list[str], matches: list[dict], rules: dict) -> dict[str, dict]:
    p = rules["points"]
    rows = {t: {"team": t, "played": 0, "won": 0, "drawn": 0, "lost": 0, "for": 0, "against": 0, "points": 0} for t in teams}
    for m in matches:
        h, a = m["home"], m["away"]
        hs, as_ = m["score"]
        winner = None
        if m.get("walkover"):  # the team that didn't show (m["walkover"]) loses; the score is the walkover score
            winner = a if m["walkover"] == h else h
            wf, wa = rules["walkover"]["for"] or 0, rules["walkover"]["against"] or 0
            hs, as_ = (wf, wa) if winner == h else (wa, wf)
        elif hs != as_:
            winner = h if hs > as_ else a
        for t, f, ag in ((h, hs, as_), (a, as_, hs)):
            r = rows[t]
            r["played"] += 1
            r["for"] += f
            r["against"] += ag
            if winner == t:
                r["won"] += 1
                r["points"] += p["win"] or 0
            elif winner is None:
                r["drawn"] += 1
                r["points"] += p["draw"] or 0
            else:
                r["lost"] += 1
                r["points"] += p["loss"] or 0
    for r in rows.values():
        r["diff"] = r["for"] - r["against"]
    return rows


def _key(tb: str, team: str, rows: dict, tied: list[str], matches: list[dict], rules: dict):
    r = rows[team]
    if tb == "goal_difference":
        return r["diff"]
    if tb == "goals_scored":
        return r["for"]
    if tb == "wins":
        return r["won"]
    if tb == "net_run_rate":
        return round(r["diff"] / max(r["played"], 1), 3)  # demo: equal overs in every match
    if tb == "head_to_head":
        among = [m for m in matches if m["home"] in tied and m["away"] in tied]
        mini = _rows(tied, among, rules)
        if len(tied) > 2 and rules.get("three_way") == "overall":
            return 0  # three or more level: head-to-head is skipped, the next tiebreaker decides
        return (mini[team]["points"], mini[team]["diff"], mini[team]["for"]) if len(tied) > 2 else mini[team]["points"]
    if tb == "lots":
        return -sum(ord(c) for c in team)  # stands in for the draw: fixed so examples don't change
    return 0  # fair play: no cards in the examples


def rank(teams: list[str], matches: list[dict], rules: dict) -> tuple[list[str], dict, list[dict]]:
    """Order a group. Returns (order, rows, decisions: how each tie was broken)."""
    rows = _rows(teams, matches, rules)
    decisions: list[dict] = []

    def split(tied: list[str], tbs: list[str]) -> list[str]:
        if len(tied) < 2 or not tbs:
            if len(tied) > 1:
                decisions.append({"teams": tied, "by": None})
            return sorted(tied)
        tb, rest = tbs[0], tbs[1:]
        keys = {t: _key(tb, t, rows, tied, matches, rules) for t in tied}
        out = []
        for k in sorted(set(keys.values()), reverse=True):
            same = [t for t in tied if keys[t] == k]
            out.extend(split(same, rest) if len(same) > 1 else same)
        if len(set(keys.values())) > 1:
            decisions.append({"teams": tied, "by": tb})
        return out

    order = []
    for pts in sorted({r["points"] for r in rows.values()}, reverse=True):
        level = sorted(t for t in teams if rows[t]["points"] == pts)
        order.extend(split(level, rules["tiebreakers"]) if len(level) > 1 else level)
    return order, rows, decisions


# ---- worked examples ---------------------------------------------------------------------

def _m(h, a, hs, as_, walkover=None):
    return {"home": h, "away": a, "score": [hs, as_], "walkover": walkover}


def _scale(sport: str, n: int) -> int:
    return n * 20 + 80 if sport == "cricket" else n * 10 + 50 if sport == "basketball" else n


def _example_sets(sport: str) -> list[dict]:
    s = lambda n: _scale(sport, n)  # noqa: E731  (cricket/basketball scores look like their sport)
    return [
        {"id": "two-level", "title": "Two teams level on points", "focus": ["A", "B"], "matches": [
            _m("A", "B", s(1), s(0)), _m("A", "C", s(1), s(0)), _m("D", "A", s(5), s(0)),
            _m("B", "C", s(3), s(0)), _m("B", "D", s(4), s(0)), _m("C", "D", s(2), s(1))]},
        {"id": "three-level", "title": "Three teams level on points", "focus": ["A", "B", "C"], "matches": [
            _m("A", "B", s(2), s(1)), _m("B", "C", s(3), s(0)), _m("C", "A", s(1), s(0)),
            _m("A", "D", s(4), s(0)), _m("B", "D", s(1), s(0)), _m("C", "D", s(2), s(0))]},
        {"id": "same-difference", "title": "Level on points and difference", "focus": ["A", "B"], "matches": [
            _m("B", "A", s(2), s(1)), _m("A", "C", s(4), s(2)), _m("A", "D", s(3), s(2)),
            _m("B", "D", s(2), s(0)), _m("C", "B", s(1), s(0)), _m("D", "C", s(1), s(0))]},
        {"id": "walkover", "title": "A walkover", "focus": ["A", "D"], "matches": [
            _m("A", "D", 0, 0, walkover="D"), _m("A", "B", s(1), s(2)), _m("A", "C", s(2), s(0)),
            _m("B", "C", s(1), s(1) if sport != "volleyball" else s(0)), _m("B", "D", s(3), s(1)), _m("C", "D", s(2), s(2) if sport != "volleyball" else s(1))]},
        {"id": "advancement", "title": "Who goes through", "focus": [], "matches": [
            _m("A", "B", s(2), s(0)), _m("A", "C", s(1), s(0)), _m("A", "D", s(3), s(1)),
            _m("B", "C", s(2), s(1)), _m("B", "D", s(0), s(1)), _m("C", "D", s(2), s(0))]},
    ]


def _names(e: dict) -> dict[str, str]:
    real = [t["name"] for t in (e.get("teams") or [])][:4]
    return {k: (real[i] if i < len(real) else f"Team {k}") for i, k in enumerate("ABCD")}


def _complete(d: dict) -> bool:
    return all(v is not None for v in (d["points"]["win"], d["points"]["draw"], d["points"]["loss"])) and bool(d["tiebreakers"])


def examples(e: dict, d: dict) -> list[dict]:
    if not _complete(d):
        return []
    names = _names(e)
    word = _score_word(e["sport"])
    out = []
    for ex in _example_sets(e["sport"]):
        order, rows, decisions = rank(list("ABCD"), ex["matches"], d)
        n = lambda t: names[t]  # noqa: E731
        if ex["id"] == "advancement":
            per = d["advancement"]["per_group"] or 0
            through = [n(t) for t in order[:per]]
            text = f"With these results the top {per} go through: {', '.join(through) or 'nobody'}." if per else \
                "Set how many teams go through to see this example."
        elif ex["id"] == "walkover":
            wf, wa = d["walkover"]["for"], d["walkover"]["against"]
            how_won = f"a {wf}–{wa} win" if e["sport"] != "cricket" else "a win (run rates unchanged)"
            text = (f"{n('D')} didn’t turn up against {n('A')}. The engine counts it as {how_won} for {n('A')} "
                    f"({d['points']['win']} points), and ranks the group {', '.join(n(t) for t in order)}.") if wf is not None \
                else "Choose how a walkover is scored to see this example."
        else:
            focus = [t for t in order if t in ex["focus"]]
            pts = rows[ex["focus"][0]]["points"]
            how = next((x for x in decisions if set(ex["focus"]) <= set(x["teams"])), None)
            by = TIEBREAKERS.get(how["by"], "nothing") if how and how["by"] else "none of the tiebreakers"
            text = (f"If {', '.join(n(t) for t in ex['focus'][:-1])} and {n(ex['focus'][-1])} finish level on {pts} points like this, "
                    f"the engine ranks them {', '.join(n(t) for t in focus)} (decided by {by.lower()}).")
        table = [{"team": n(t), "played": rows[t]["played"], "won": rows[t]["won"], "drawn": rows[t]["drawn"],
                  "lost": rows[t]["lost"], "for": rows[t]["for"], "against": rows[t]["against"], "diff": rows[t]["diff"],
                  "points": rows[t]["points"], "highlight": t in ex["focus"]} for t in order]
        results = [{"home": n(m["home"]), "away": n(m["away"]), "score": m["score"], "walkover": n(m["walkover"]) if m["walkover"] else None}
                   for m in ex["matches"]]
        fp = hashlib.sha1(json.dumps([text, table], sort_keys=True).encode()).hexdigest()[:10]
        out.append({"id": ex["id"], "title": ex["title"], "text": text, "table": table, "results": results,
                    "score_word": word, "fingerprint": fp})
    return out


# ---- questions ---------------------------------------------------------------------------

def questions(e: dict, d: dict) -> list[dict]:
    text = (e.get("rules_text") or "").lower()
    found = set((e.get("rules") or {}).get("uncertain", [])) if e.get("rules") else {"tiebreakers", "qualifyCount"}
    qs = []
    cricket = e["sport"] == "cricket"
    if "tiebreakers" in found:
        orders = ([["net_run_rate", "head_to_head", "lots"], ["head_to_head", "net_run_rate", "lots"], ["wins", "net_run_rate", "lots"]] if cricket
                  else [["goal_difference", "goals_scored", "head_to_head", "lots"], ["head_to_head", "goal_difference", "goals_scored", "lots"],
                        ["goal_difference", "head_to_head", "goals_scored", "lots"]])
        qs.append({"id": "tiebreakers", "text": "Your rulebook doesn’t say how teams level on points are ranked. Choose the order:",
                   "options": [{"id": str(i), "label": " → ".join(TIEBREAKERS[k] for k in o), "value": o} for i, o in enumerate(orders)]})
    if "three" not in text and "mini" not in text:
        qs.append({"id": "three_way", "text": "Your rulebook doesn’t say how a three-way tie is broken. Choose one:",
                   "options": [{"id": "mini_league", "label": "A mini-league of the matches between the tied teams", "value": "mini_league"},
                               {"id": "overall", "label": "Skip head-to-head and use the next tiebreaker for all of them", "value": "overall"}]})
    if not any(w in text for w in QUOTE_WORDS["walkover"]):
        opts = [(3, 0), (5, 0), (1, 0)] if e["sport"] in ("football", "floorball", "ice-hockey") else \
            [(20, 0), (2, 0)] if e["sport"] in ("basketball", "volleyball") else [(0, 0)]
        label = (lambda a, b: f"Counted as a {a}–{b} win") if e["sport"] != "cricket" else (lambda a, b: "A win with full points; run rates unchanged")
        qs.append({"id": "walkover", "text": "Your rulebook doesn’t say how a walkover is scored. Choose one:",
                   "options": [{"id": f"{a}-{b}", "label": label(a, b), "value": [a, b]} for a, b in opts]})
    if "qualifyCount" in found:
        qs.append({"id": "advancement", "text": "How many teams go through from each group?",
                   "options": [{"id": str(n), "label": f"The top {n}", "value": n} for n in (1, 2, 3)]})
    return qs


def apply_answer(d: dict, qid: str, value) -> None:
    if qid == "tiebreakers":
        d["tiebreakers"] = list(value)
    elif qid == "three_way":
        d["three_way"] = value
    elif qid == "walkover":
        d["walkover"] = {"for": value[0], "against": value[1]}
    elif qid == "advancement":
        d["advancement"]["per_group"] = value


# ---- tests -------------------------------------------------------------------------------

def tests(e: dict, d: dict) -> list[dict]:
    out = []

    def t(tid, name, ok, detail, skipped=False):
        out.append({"id": tid, "name": name, "result": "skipped" if skipped else "pass" if ok else "fail", "detail": detail})

    p = d["points"]
    if None in (p["win"], p["draw"], p["loss"]):
        t("points", "Points are set", False, "Set the points for a win, a draw and a loss.")
    else:
        t("points", "A win is worth more than a draw, a draw at least a loss", p["win"] > p["draw"] >= p["loss"],
          f"Win {p['win']}, draw {p['draw']}, loss {p['loss']}.")
    tbs = d["tiebreakers"]
    t("decider", "Every tie can be broken", bool(tbs) and tbs[-1] == "lots",
      "The list ends with drawing lots." if tbs and tbs[-1] == "lots"
      else "Two teams level on everything can’t be separated: add “Drawing lots” as the last tiebreaker.")
    t("duplicates", "No tiebreaker is used twice", len(tbs) == len(set(tbs)), "Each tiebreaker appears once." if len(tbs) == len(set(tbs))
      else "Remove the repeated tiebreaker.")
    if _complete(d):
        try:
            for ex in _example_sets(e["sport"]):
                order, _, _ = rank(list("ABCD"), ex["matches"], d)
                assert sorted(order) == list("ABCD")
            cyc = [_m("A", "B", 1, 0), _m("B", "C", 1, 0), _m("C", "A", 1, 0)]  # a perfect three-way circle
            order, _, _ = rank(list("ABC"), cyc, d)
            t("three_way", "A perfect three-way tie still gets an order", len(order) == 3, "Engine order: " + ", ".join(order) + ".")
        except Exception as exc:  # noqa: BLE001  (shown to the organiser as a failed test)
            t("three_way", "A perfect three-way tie still gets an order", False, f"The engine stopped: {exc}.")
    else:
        t("three_way", "A perfect three-way tie still gets an order", False, "Needs the points and tiebreakers.", skipped=True)
    wo = d["walkover"]
    if wo["for"] is None:
        t("walkover", "A walkover counts as a win", False, "Choose how a walkover is scored.")
    else:
        rows = _rows(["A", "B"], [_m("A", "B", 0, 0, walkover="B")], d) if _complete(d) else None
        ok = rows is not None and rows["A"]["won"] == 1 and rows["A"]["points"] == p["win"] and \
            (e["sport"] == "cricket" or wo["for"] > wo["against"])
        t("walkover", "A walkover counts as a win", ok, f"Scored {wo['for']}–{wo['against']}." if e["sport"] != "cricket" else "Full points, run rate unchanged.")
    groups = max(len(e.get("groups") or []), 1)
    teams = len(e.get("teams") or []) or e.get("planned_teams", 0)
    per = d["advancement"]["per_group"]
    if per is None:
        t("advancement", "Advancement fits the groups", False, "Set how many teams go through from each group.")
    else:
        smallest = min((sum(1 for x in e["teams"] if x["group"] == g["id"]) for g in e["groups"]), default=teams // groups) \
            if e.get("teams") else teams // groups
        t("advancement", "Advancement fits the groups", 0 < per < max(smallest, 2),
          f"Top {per} of each group; the smallest group has {smallest} teams.")
        ko = d["format"]["knockout"]
        need = {"none": 0, "final": 2, "semis": 4, "quarters": 8}.get(ko or "none", 0)
        t("knockout", "The knockout stage gets the right number of teams", need == 0 or per * groups == need,
          f"{per * groups} teams go through; {KNOCKOUT.get(ko or 'none', 'the knockout stage').lower()} needs {need or 'none'}.")
    fx = e.get("fixtures") or []
    if fx and e.get("teams"):
        expected = 0
        for g in e["groups"]:
            n = sum(1 for x in e["teams"] if x["group"] == g["id"]) if len(e["groups"]) > 1 else len(e["teams"])
            expected += n * (n - 1) // 2 * (2 if d["format"]["round_robin"] == "double" else 1)
        t("fixtures", "The fixtures match the format", len(fx) == expected, f"{len(fx)} matches in the fixtures; the format needs {expected}.")
    else:
        t("fixtures", "The fixtures match the format", False, "No fixtures yet.", skipped=True)
    m = d["match"]
    t("match", "Match length is set", bool(m["minutes"]), f"{m['minutes']} minutes." if m["minutes"] else "Set the match length.")
    return out


# ---- cards (plain language + controls) ---------------------------------------------------

def cards(e: dict, d: dict) -> list[dict]:
    text = e.get("rules_text") or ""
    groups = max(len(e.get("groups") or []), 1)
    word = _score_word(e["sport"])
    p, adv, m, wo, f = d["points"], d["advancement"], d["match"], d["walkover"], d["format"]
    unset = "not set"
    plain = {
        "format": f"{groups} group{'s' if groups > 1 else ''}; everyone plays everyone in their group "
                  f"{'twice' if f['round_robin'] == 'double' else 'once' if f['round_robin'] else '(not set)'}. "
                  f"{KNOCKOUT.get(f['knockout'], 'Knockout stage not set')}.",
        "points": f"A win gives {p['win'] if p['win'] is not None else unset}, a draw {p['draw'] if p['draw'] is not None else unset} "
                  f"and a loss {p['loss'] if p['loss'] is not None else unset} points.",
        "tiebreakers": "Teams level on points are ranked by " + (" → ".join(TIEBREAKERS[k].lower() for k in d["tiebreakers"]) or "nothing yet")
                       + (". Three-way ties: " + ("a mini-league between the tied teams." if d["three_way"] == "mini_league"
                                                   else "head-to-head skipped." if d["three_way"] == "overall" else "not decided.")),
        "advancement": f"The top {adv['per_group']} of each group go through." if adv["per_group"] else "Who goes through is not set.",
        "match": (f"Matches last {m['minutes']} minutes." if m["minutes"] else "Match length is not set.")
                 + (" Extra time if needed." if m["extra_time"] else "") + (" Then penalties." if m["penalties"] else ""),
        "walkover": (f"A walkover counts as a {wo['for']}–{wo['against']} win." if e["sport"] != "cricket" else "A walkover counts as a win with full points.")
                    if wo["for"] is not None else "How a walkover is scored is not set.",
    }
    fields = {
        "format": [{"key": "format.round_robin", "label": "Group matches", "type": "select", "value": f["round_robin"],
                    "options": [{"value": "single", "label": "Everyone plays everyone once"}, {"value": "double", "label": "Everyone plays everyone twice"}]},
                   {"key": "format.knockout", "label": "After the groups", "type": "select", "value": f["knockout"],
                    "options": [{"value": k, "label": v} for k, v in KNOCKOUT.items()]}],
        "points": [{"key": f"points.{k}", "label": f"Points for a {k}", "type": "number", "value": p[k], "min": 0, "max": 10}
                   for k in ("win", "draw", "loss")],
        "tiebreakers": [{"key": "tiebreakers", "label": "Tiebreakers, in order", "type": "order", "value": d["tiebreakers"],
                         "options": [{"value": k, "label": v} for k, v in TIEBREAKERS.items()
                                     if not (k == "net_run_rate" and e["sport"] != "cricket") and not (k in ("goal_difference", "goals_scored") and e["sport"] == "cricket")]},
                        {"key": "three_way", "label": "Three-way ties", "type": "select", "value": d["three_way"],
                         "options": [{"value": "mini_league", "label": "Mini-league of the tied teams’ matches"},
                                     {"value": "overall", "label": "Skip head-to-head, use the next tiebreaker"}]}],
        "advancement": [{"key": "advancement.per_group", "label": "Teams through from each group", "type": "number", "value": adv["per_group"], "min": 1, "max": 8}],
        "match": [{"key": "match.minutes", "label": "Match length (minutes)", "type": "number", "value": m["minutes"], "min": 10, "max": 300},
                  {"key": "match.extra_time", "label": "Extra time in knockout games", "type": "select", "value": m["extra_time"],
                   "options": [{"value": True, "label": "Yes"}, {"value": False, "label": "No"}]},
                  {"key": "match.penalties", "label": "Penalties / super over if still level", "type": "select", "value": m["penalties"],
                   "options": [{"value": True, "label": "Yes"}, {"value": False, "label": "No"}]}],
        "walkover": [{"key": "walkover.for", "label": f"{word.title()}s for the team that showed up", "type": "number", "value": wo["for"], "min": 0, "max": 50},
                     {"key": "walkover.against", "label": f"{word.title()}s for the team that didn’t", "type": "number", "value": wo["against"], "min": 0, "max": 50}],
    }
    titles = {"format": "Format", "points": "Points", "tiebreakers": "Tiebreakers, in order", "advancement": "Who goes through",
              "match": "Match rules", "walkover": "Walkovers"}
    uncertain = set((e.get("rules") or {}).get("uncertain", []))
    from_text = {"points": not ({"pointsWin", "pointsDraw"} & uncertain), "tiebreakers": "tiebreakers" not in uncertain,
                 "advancement": "qualifyCount" not in uncertain, "match": "matchMinutes" not in uncertain}
    out = []
    for gid in titles:
        q = quote(text, gid)
        out.append({"id": gid, "title": titles[gid], "plain": plain[gid], "quote": q,
                    "source": "rulebook" if q and from_text.get(gid, True) else "default" if e.get("rules") else "manual",
                    "fields": fields[gid]})
    return out


# ---- summary / draft changes / confirm ---------------------------------------------------

def summary(store: FeedStore, event_id: str, e: dict) -> dict:
    tick_job(store, e)
    job = e.get("rules_job")
    versions = e.get("rule_versions", [])
    base = {"event_id": event_id, "event_name": e["name"], "sport": e["sport"],
            "rulebook": e.get("rulebook"), "versions": [{k: v[k] for k in ("version", "confirmed_at", "confirmed_by")} for v in versions],
            "updated_at": store.now}
    if e.get("rules_draft") is None and (not job or job["status"] != "done"):
        state = "reading" if job and job["status"] == "reading" else "failed" if job and job["status"] == "failed" else "none"
        return {**base, "state": state, "progress": job["progress"] if job else 0, "draft": None, "cards": [], "questions": [],
                "answers": {}, "examples": [], "marks": {}, "tests": [], "can_confirm": False,
                "blockers": ["The rules haven’t been read yet."], "changed_since_confirm": False}
    d = draft(store, e)
    qs = questions(e, d)
    answers = e.setdefault("rules_answers", {})
    exs = examples(e, d)
    marks = e.setdefault("rules_marks", {})
    for ex in exs:  # a mark only counts for the example as it is now
        mk = marks.get(ex["id"])
        ex["mark"] = mk if mk and mk.get("fingerprint") == ex["fingerprint"] else {"status": "pending", "note": ""}
    tst = tests(e, d)
    blockers = []
    open_q = [q for q in qs if q["id"] not in answers]
    if open_q:
        blockers.append(f"Answer {len(open_q)} question{'s' if len(open_q) > 1 else ''} from the AI.")
    if not exs:
        blockers.append("Fill in the points and tiebreakers so the engine can work through examples.")
    unmarked = [x for x in exs if x["mark"]["status"] != "correct"]
    if unmarked:
        blockers.append(f"Mark {len(unmarked)} example{'s' if len(unmarked) > 1 else ''} as correct "
                        f"({sum(1 for x in unmarked if x['mark']['status'] == 'incorrect')} marked not correct).")
    failed = [x for x in tst if x["result"] == "fail"]
    if failed:
        blockers.append(f"Fix {len(failed)} failing test{'s' if len(failed) > 1 else ''}.")
    last = versions[-1]["rules"] if versions else None
    return {**base, "state": "confirmed" if last == d and not blockers else "draft", "progress": 100, "draft": d,
            "cards": cards(e, d), "questions": qs, "answers": answers, "examples": exs, "tests": tst,
            "can_confirm": not blockers and last != d, "blockers": blockers, "changed_since_confirm": bool(versions) and last != d}


def _set(d: dict, key: str, value) -> None:
    if key in ("tiebreakers", "three_way"):
        d[key] = value
        return
    group, field = key.split(".")
    d[group][field] = value


ALLOWED = {"format.round_robin": {"single", "double"}, "format.knockout": set(KNOCKOUT), "three_way": {"mini_league", "overall"},
           "match.extra_time": {True, False}, "match.penalties": {True, False}}
NUMBERS = {"points.win": (0, 10), "points.draw": (0, 10), "points.loss": (0, 10), "advancement.per_group": (1, 8),
           "match.minutes": (10, 300), "walkover.for": (0, 50), "walkover.against": (0, 50)}


def patch(store: FeedStore, e: dict, body) -> None:
    if body.manual:
        e["rules_draft"] = _from_extracted(e, None)
        e["rules"] = None
        e["rules_answers"], e["rules_marks"] = {}, {}
        e["rules_job"] = {"status": "done", "progress": 100, "step": "Entered by hand", "started_at": store.now}
        e["status"] = "rules_pending"
        return
    d = draft(store, e)
    if d is None:
        raise HTTPException(409, {"code": "no_draft", "message": "The rules haven’t been read yet."})
    new = deepcopy(d)
    for key, value in (body.values or {}).items():
        if key == "tiebreakers":
            if not isinstance(value, list) or any(v not in TIEBREAKERS for v in value):
                raise HTTPException(422, {"code": "tiebreakers", "message": "Unknown tiebreaker."})
        elif key in NUMBERS:
            lo, hi = NUMBERS[key]
            if not isinstance(value, int) or not lo <= value <= hi:
                raise HTTPException(422, {"code": "value", "field": key, "message": f"Choose a number from {lo} to {hi}."})
        elif key in ALLOWED:
            if value not in ALLOWED[key]:
                raise HTTPException(422, {"code": "value", "field": key, "message": "Pick one of the options."})
        else:
            raise HTTPException(422, {"code": "field", "field": key, "message": "Unknown rule."})
        _set(new, key, value)
    qs = {q["id"]: q for q in questions(e, new)}
    for qid, option in (body.answers or {}).items():
        q = qs.get(qid)
        opt = next((o for o in q["options"] if o["id"] == option), None) if q else None
        if opt is None:
            raise HTTPException(422, {"code": "answer", "message": "Pick one of the choices."})
        e["rules_answers"][qid] = option
        apply_answer(new, qid, opt["value"])
    e["rules_draft"] = new
    exs = {x["id"]: x for x in examples(e, new)}
    for ex_id, mark in (body.marks or {}).items():
        if ex_id not in exs:
            raise HTTPException(422, {"code": "example", "message": "That example changed. Look at it again."})
        if mark.status == "incorrect" and not (mark.note or "").strip():
            raise HTTPException(422, {"code": "note", "message": "Tell us what’s wrong with the example."})
        e["rules_marks"][ex_id] = {"status": mark.status, "note": (mark.note or "").strip(), "fingerprint": exs[ex_id]["fingerprint"]}


def confirm(store: FeedStore, e: dict, session: Session) -> dict:
    s = summary(store, "", e)
    if not s["can_confirm"]:
        raise HTTPException(409, {"code": "not_ready", "message": " ".join(s["blockers"]) or "Nothing changed since the last version.",
                                  "blockers": s["blockers"]})
    versions = e.setdefault("rule_versions", [])
    v = {"version": len(versions) + 1, "confirmed_at": store.now, "confirmed_by": session.name, "rules": deepcopy(e["rules_draft"]),
         "notes": {k: m["note"] for k, m in e["rules_marks"].items() if m["note"]}}
    versions.append(v)
    e["status"] = "scheduled"
    e["next_step"] = f"Rules confirmed (version {v['version']}). Publish the event when the teams are ready."
    return {k: v[k] for k in ("version", "confirmed_at", "confirmed_by")}
