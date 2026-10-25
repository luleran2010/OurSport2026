"""Football (v1): rules, results, team statistics and event validation.

Analysis and live moments are added by T-017.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, model_validator

from engine.model import EventLite, Fixture, LiveStateLite, MatchResult, TeamStats
from engine.rules.base import RuleModel
from engine.rules.config import RuleConfig, Tiebreaker
from engine.rules.issues import Issue
from engine.sports.base import InvalidEvent, MarginAxis

__all__ = ["FOOTBALL", "Cards", "FootballResult", "FootballSport", "InvalidEvent"]

DecidedBy = Literal["regulation", "extra_time", "penalties"]

EVENT_TYPES = frozenset(
    {
        "period_start",
        "period_end",
        "goal",
        "penalty_missed",
        "yellow_card",
        "second_yellow",
        "red_card",
        "substitution",
        "shootout_kick",
        "undo",
    }
)
TEAM_EVENTS = frozenset(
    {
        "goal",
        "penalty_missed",
        "yellow_card",
        "second_yellow",
        "red_card",
        "substitution",
        "shootout_kick",
    }
)
# Events a player who has been sent off can no longer be involved in.
_PLAYING_EVENTS = frozenset(
    {"goal", "penalty_missed", "yellow_card", "second_yellow", "red_card", "shootout_kick"}
)
GOAL_KINDS = frozenset({"open_play", "penalty", "own_goal", "free_kick", "header"})
EXTRA_TIME_PERIODS = 2


# --- configuration ---------------------------------------------------------------------------


class FootballMatchRules(RuleModel):
    """`RuleConfig.match` for football; small-sided and junior formats are configuration."""

    periods: int = Field(default=2, ge=1, le=4)
    period_minutes: int = Field(default=45, ge=1, le=60)
    half_time_minutes: int = Field(default=15, ge=0, le=30)  # break between periods
    extra_time: bool = False
    extra_time_minutes: int = Field(default=15, ge=1, le=30)  # per extra-time period
    penalties_in_knockout: bool = True
    squad_size: int = Field(default=11, ge=3, le=11)
    rolling_substitutions: bool = True


class FootballWalkover(RuleModel):
    """Score credited to the team that wins by walkover (default 3-0)."""

    score_for: int = Field(default=3, ge=1)
    score_against: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _winner_scores_more(self) -> Self:
        if self.score_for <= self.score_against:
            raise ValueError("a walkover must credit the winner with more goals")
        return self


# --- results ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cards:
    """Disciplinary events for one team in one match.

    `yellow` counts cautions that did not lead to a sending-off; a player's second caution is
    counted once, as `second_yellow` (the FIFA/UEFA fair-play convention).
    """

    yellow: int = 0
    second_yellow: int = 0
    red: int = 0

    def __post_init__(self) -> None:
        if min(self.yellow, self.second_yellow, self.red) < 0:
            raise ValueError("card counts cannot be negative")


@dataclass(frozen=True)
class FootballResult:
    """Final score after regulation (and extra time if played), plus any shootout."""

    home_goals: int
    away_goals: int
    decided_by: DecidedBy = "regulation"
    home_penalties: int | None = None
    away_penalties: int | None = None
    home_cards: Cards = field(default_factory=Cards)
    away_cards: Cards = field(default_factory=Cards)

    def __post_init__(self) -> None:
        if self.home_goals < 0 or self.away_goals < 0:
            raise ValueError("goals cannot be negative")
        has_penalties = self.home_penalties is not None or self.away_penalties is not None
        level = self.home_goals == self.away_goals
        if self.decided_by != "penalties":
            if has_penalties:
                raise ValueError("penalty scores belong only to a result decided by a shootout")
            if self.decided_by == "extra_time" and level:
                raise ValueError("a result decided in extra time cannot be level")
            return
        if not level:
            raise ValueError("a shootout only follows a level score")
        if self.home_penalties is None or self.away_penalties is None:
            raise ValueError("a shootout result needs the shootout score")
        if min(self.home_penalties, self.away_penalties) < 0:
            raise ValueError("shootout goals cannot be negative")
        if self.home_penalties == self.away_penalties:
            raise ValueError("a shootout must have a winner")


def _football(result: MatchResult) -> FootballResult:
    if not isinstance(result.outcome, FootballResult):
        raise TypeError(f"match {result.match_id} does not hold a football result")
    return result.outcome


def _side(result: MatchResult, team: str) -> Literal["home", "away"]:
    if team == result.home:
        return "home"
    if team == result.away:
        return "away"
    raise ValueError(f"team {team} is not in match {result.match_id}")


def _issues_from(exc: ValidationError, prefix: str, code: str) -> list[Issue]:
    return [
        Issue(code, ".".join([prefix, *(str(part) for part in error["loc"])]), error["msg"])
        for error in exc.errors()
    ]


# --- the sport module ------------------------------------------------------------------------


class FootballSport:
    code = "football"
    event_types: frozenset[str] = EVENT_TYPES
    outcome_keys: tuple[str, ...] = ("win", "draw", "loss")
    supported_tiebreakers: frozenset[Tiebreaker] = frozenset(Tiebreaker)
    fair_play_keys: tuple[str, ...] = ("yellow", "second_yellow", "red")

    # rules

    def match_rules(self, match: Mapping[str, Any]) -> FootballMatchRules:
        return FootballMatchRules.model_validate(match)

    def match_rules_issues(self, match: Mapping[str, Any]) -> list[Issue]:
        try:
            self.match_rules(match)
        except ValidationError as exc:
            return _issues_from(exc, "match", "invalid_match_rules")
        return []

    def walkover_issues(self, walkover: Mapping[str, Any]) -> list[Issue]:
        try:
            FootballWalkover.model_validate(walkover)
        except ValidationError as exc:
            return _issues_from(exc, "walkover", "invalid_walkover")
        return []

    def knockout_issues(self, match: Mapping[str, Any], uses_extra_time: bool) -> list[Issue]:
        try:
            rules = self.match_rules(match)
        except ValidationError:
            return []  # reported by match_rules_issues
        issues = []
        if not rules.penalties_in_knockout:
            issues.append(
                Issue(
                    "knockout_draws_undecided",
                    "match.penalties_in_knockout",
                    "knockout matches can end level, so a penalty shootout is needed "
                    "to decide them",
                )
            )
        if uses_extra_time and not rules.extra_time:
            issues.append(
                Issue(
                    "extra_time_not_configured",
                    "match.extra_time",
                    "the knockout uses extra time, but the match rules have no extra time",
                )
            )
        return issues

    def match_duration_minutes(self, match: Mapping[str, Any]) -> int:
        rules = self.match_rules(match)
        return rules.periods * rules.period_minutes + (rules.periods - 1) * rules.half_time_minutes

    # results

    def outcome_key(self, result: MatchResult, team: str) -> str:
        """Win/draw/loss on the score after regulation and extra time.

        A shootout does not change the outcome for points: a level match is a draw.
        """
        score = _football(result)
        side = _side(result, team)
        own, other = (
            (score.home_goals, score.away_goals)
            if side == "home"
            else (score.away_goals, score.home_goals)
        )
        if own > other:
            return "win"
        return "draw" if own == other else "loss"

    def knockout_winner(self, result: MatchResult) -> str:
        score = _football(result)
        if score.home_goals != score.away_goals:
            return result.home if score.home_goals > score.away_goals else result.away
        if score.home_penalties is not None and score.away_penalties is not None:
            return result.home if score.home_penalties > score.away_penalties else result.away
        raise ValueError(f"match {result.match_id} is level with no shootout: no winner")

    def walkover_result(self, rules: RuleConfig, winner: Literal["home", "away"]) -> FootballResult:
        credited = FootballWalkover.model_validate(rules.walkover)
        if winner == "home":
            return FootballResult(credited.score_for, credited.score_against)
        return FootballResult(credited.score_against, credited.score_for)

    def team_stats(self, results: Sequence[MatchResult], team: str, rules: RuleConfig) -> TeamStats:
        outcomes: Counter[str] = Counter()
        score_for = score_against = away_score_for = fair_play = 0
        weights = rules.fair_play_points
        for result in results:
            if team not in (result.home, result.away):
                continue
            score = _football(result)
            at_home = team == result.home
            own_goals, other_goals = (
                (score.home_goals, score.away_goals)
                if at_home
                else (score.away_goals, score.home_goals)
            )
            cards = score.home_cards if at_home else score.away_cards
            outcomes[self.outcome_key(result, team)] += 1
            score_for += own_goals
            score_against += other_goals
            if not at_home:
                away_score_for += own_goals
            fair_play += (
                cards.yellow * weights.get("yellow", 0)
                + cards.second_yellow * weights.get("second_yellow", 0)
                + cards.red * weights.get("red", 0)
            )
        return TeamStats(
            team=team,
            played=sum(outcomes.values()),
            won=outcomes["win"],
            drawn=outcomes["draw"],
            lost=outcomes["loss"],
            outcome_counts=dict(outcomes),
            points=sum(rules.points.table.get(key, 0) * n for key, n in outcomes.items()),
            score_for=score_for,
            score_against=score_against,
            away_score_for=away_score_for,
            fair_play_points=fair_play,
        )

    def metric(self, tiebreaker: Tiebreaker, stats: TeamStats) -> float | None:
        match tiebreaker:
            case Tiebreaker.POINTS:
                return stats.points
            case Tiebreaker.POINTS_PER_GAME:
                return stats.points / stats.played if stats.played else 0.0
            case Tiebreaker.WINS:
                return stats.won
            case Tiebreaker.SCORE_DIFF:
                return stats.score_diff
            case Tiebreaker.SCORE_FOR:
                return stats.score_for
            case Tiebreaker.AWAY_SCORE_FOR:
                return stats.away_score_for
            case Tiebreaker.FAIR_PLAY:
                return -stats.fair_play_points
            case _:
                # Head-to-head is computed by standings on a mini-table; lots are never a metric.
                return None

    # scenarios

    def hypothetical_outcomes(
        self, fixture: Fixture, rules: RuleConfig, *, knockout: bool
    ) -> Sequence[FootballResult]:
        if knockout:
            return (FootballResult(1, 0), FootballResult(0, 1))
        return (FootballResult(1, 0), FootballResult(0, 0), FootballResult(0, 1))

    def margin_axis(self) -> MarginAxis:
        return MarginAxis(unit="goal_difference", max_margin=10, make=FootballResult)

    # live events

    def credited_team(self, state: LiveStateLite, event: EventLite) -> str:
        """The team a goal counts for: an own goal counts for the opponents."""
        if event.payload.get("kind") == "own_goal":
            return state.away if event.team == state.home else state.home
        assert event.team is not None
        return event.team

    def validate_event(
        self,
        state: LiveStateLite,
        event: EventLite,
        rules: RuleConfig,
        *,
        allow_after_full_time: bool = False,
    ) -> None:
        if event.type not in EVENT_TYPES:
            raise InvalidEvent("invalid_event_type", f"'{event.type}' is not a football event")
        if state.finished and not allow_after_full_time:
            raise InvalidEvent(
                "event_after_full_time", "the match is over; only an admin correction can change it"
            )
        if event.type == "undo":
            target = event.payload.get("undoes_seq")
            if not isinstance(target, int) or not 0 < target < event.seq:
                raise InvalidEvent("invalid_undo", "an undo must point at an earlier event")
            return
        if event.type in ("period_start", "period_end"):
            self._check_period(event, rules)
            return
        if event.team not in (state.home, state.away):
            raise InvalidEvent("team_not_in_match", "the event's team is not playing this match")
        if (
            event.player is not None
            and event.player in state.sent_off
            and (event.type in _PLAYING_EVENTS)
        ):
            raise InvalidEvent("player_already_sent_off", "that player has already been sent off")
        if event.type == "goal" and event.payload.get("kind", "open_play") not in GOAL_KINDS:
            raise InvalidEvent(
                "invalid_payload", f"goal kind must be one of: {', '.join(sorted(GOAL_KINDS))}"
            )
        if event.type == "shootout_kick":
            if not state.knockout:
                raise InvalidEvent(
                    "shootout_not_allowed", "penalty shootouts only happen in knockout matches"
                )
            if not isinstance(event.payload.get("scored"), bool):
                raise InvalidEvent("invalid_payload", "a shootout kick needs scored: true/false")

    def _check_period(self, event: EventLite, rules: RuleConfig) -> None:
        match_rules = self.match_rules(rules.match)
        last = match_rules.periods + (EXTRA_TIME_PERIODS if match_rules.extra_time else 0)
        period = event.payload.get("period")
        if not isinstance(period, int) or not 1 <= period <= last:
            raise InvalidEvent("invalid_payload", f"period must be between 1 and {last}")

    # replay and moments

    def apply_event(
        self, state: LiveStateLite, event: EventLite, rules: RuleConfig
    ) -> LiveStateLite:
        """The live state after one (already validated) event."""
        if event.type == "goal":
            if self.credited_team(state, event) == state.home:
                return replace(state, home_goals=state.home_goals + 1)
            return replace(state, away_goals=state.away_goals + 1)
        if event.type in ("red_card", "second_yellow") and event.player is not None:
            return replace(state, sent_off=state.sent_off | {event.player})
        if event.type == "period_start":
            return replace(state, period=int(event.payload["period"]))
        if event.type == "period_end":
            return replace(
                state, finished=self._ends_match(state, int(event.payload["period"]), rules)
            )
        if event.type == "shootout_kick" and event.payload.get("scored"):
            if event.team == state.home:
                return replace(state, home_shootout=state.home_shootout + 1)
            return replace(state, away_shootout=state.away_shootout + 1)
        return state

    def _ends_match(self, state: LiveStateLite, period: int, rules: RuleConfig) -> bool:
        """Whether the end of `period` is full time (a level knockout goes on)."""
        regulation = self.match_rules(rules.match).periods
        if period < regulation:
            return False
        return not state.knockout or state.home_goals != state.away_goals

    def replay(
        self,
        home: str,
        away: str,
        events: Sequence[EventLite],
        rules: RuleConfig,
        *,
        knockout: bool = False,
    ) -> LiveStateLite:
        """The live state from every event in order; undone events are skipped."""
        undone = {e.payload.get("undoes_seq") for e in events if e.type == "undo"}
        state = LiveStateLite(home, away, 0, 0, 0, knockout)
        for event in sorted(events, key=lambda e: e.seq):
            if event.type != "undo" and event.seq not in undone:
                state = self.apply_event(state, event, rules)
        return state

    def result_of(self, state: LiveStateLite, rules: RuleConfig) -> FootballResult:
        """The final result a finished live state stands for."""
        if state.home_shootout or state.away_shootout:
            return FootballResult(
                state.home_goals,
                state.away_goals,
                "penalties",
                state.home_shootout,
                state.away_shootout,
            )
        extra = state.period > self.match_rules(rules.match).periods
        return FootballResult(
            state.home_goals, state.away_goals, "extra_time" if extra else "regulation"
        )

    def detect_moments(
        self,
        before: LiveStateLite,
        after: LiveStateLite,
        event: EventLite,
        rules: RuleConfig | None = None,
    ) -> list[str]:
        """What a fan would call a moment (docs/06-live.md, Moment detection). Football's
        moments need no rules; sports built on it may (futsal's foul limit)."""
        moments: list[str] = []
        if event.type == "goal":
            moments.append("penalty_scored" if event.payload.get("kind") == "penalty" else "goal")
            lead_before = before.home_goals - before.away_goals
            lead_after = after.home_goals - after.away_goals
            if lead_after == 0:
                moments.append("equaliser")
            elif lead_before != 0 and (lead_before > 0) != (lead_after > 0):
                moments.append("lead_change")
        elif event.type == "penalty_missed":
            moments.append("penalty_missed")
        elif event.type in ("red_card", "second_yellow"):
            moments.append("red_card")
        elif event.type == "period_start" and event.payload.get("period") == 1:
            moments.append("kick_off")
        elif event.type == "period_end":
            if after.finished:
                moments.append("full_time")
            elif event.payload.get("period") == 1:
                moments.append("half_time")
        return moments


FOOTBALL = FootballSport()
