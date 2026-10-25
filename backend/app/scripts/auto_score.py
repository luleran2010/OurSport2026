"""Generate synthetic scoring events for a local OurSport demo match.

    uv run python -m app.scripts.auto_score
    uv run python -m app.scripts.auto_score --interval 40 --count 10
    uv run python -m app.scripts.auto_score --match-id <id> --apply --start

By default this is a dry run. It emits configured period boundaries and stops at
full time without finishing the match. To apply events, use --apply and type DEMO
when prompted. The scorer URL (including its pass token) is requested without
echo; OURSPORT_SCORER_URL may be used for non-interactive runs. Only loopback
URLs are accepted so the synthetic scorer cannot write to a production service.
"""

import argparse
import getpass
import json
import os
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SYNTHETIC_BUTTON_IDS = {
    "goal",
    "penalty_goal",
    "own_goal",
    "penalty_missed",
    "yellow_card",
    "second_yellow",
    "red_card",
    "substitution",
    "foul",
}
EVENT_WEIGHTS = {
    "goal": 14,
    "penalty_goal": 1,
    "own_goal": 1,
    "penalty_missed": 2,
    "yellow_card": 12,
    "second_yellow": 1,
    "red_card": 1,
    "substitution": 28,
    "foul": 40,
}


class ScorerClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"{self.base_url}/api/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Pass {self.token}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail", exc.reason)
            except (json.JSONDecodeError, AttributeError):
                detail = exc.reason
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
            raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from None
        except URLError as exc:
            raise RuntimeError(f"Could not reach the local scorer API: {exc.reason}") from None


def client_from_scorer_url(value: str) -> ScorerClient:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in LOCAL_HOSTS:
        raise ValueError("The scorer URL must use http(s) on localhost or a loopback address.")
    if parsed.username or parsed.password:
        raise ValueError("Do not include credentials in the scorer URL's authority.")
    tokens = parse_qs(parsed.query).get("pass", [])
    if len(tokens) != 1 or not tokens[0]:
        raise ValueError("The scorer URL must contain exactly one non-empty pass query parameter.")
    return ScorerClient(f"{parsed.scheme}://{parsed.netloc}", tokens[0])


def select_match(matches: list[dict[str, Any]], requested_id: str | None) -> dict[str, Any]:
    available = [
        match for match in matches
        if match["status"] in {"scheduled", "postponed", "live"}
        and match["data_level"] == "events"
        and match["home_team_id"]
        and match["away_team_id"]
    ]
    if requested_id:
        match = next((item for item in available if item["match_id"] == requested_id), None)
        if match is None:
            raise ValueError(
                "That match is not an available live-events match for this scorer pass."
            )
        return match
    if not available:
        raise ValueError("This scorer pass has no eligible live-events matches today.")
    if len(available) == 1:
        return available[0]

    print("Choose the dedicated demo match:")
    for index, match in enumerate(available, start=1):
        home = match.get("home") or {}
        away = match.get("away") or {}
        print(
            f"  {index}. {home.get('name', 'Home')} v {away.get('name', 'Away')} "
            f"({match['code']}, {match['status']}, {match['match_id']})"
        )
    try:
        choice = int(input("Match number: "))
    except ValueError:
        raise ValueError("Enter one of the listed match numbers.") from None
    if not 1 <= choice <= len(available):
        raise ValueError("The selected match number is out of range.")
    return available[choice - 1]


def event_button(pad: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    buttons = [
        button for button in pad["buttons"]
        if button["id"] in SYNTHETIC_BUTTON_IDS
        and button["group"] in {"score", "play", "discipline"}
        and (not button.get("knockout_only") or match["stage"] != "group")
    ]
    if not buttons:
        raise ValueError(f"No supported synthetic events are available for {pad['sport']}.")
    weights = [EVENT_WEIGHTS[button["id"]] for button in buttons]
    return random.choices(buttons, weights=weights, k=1)[0]


def clock_seconds(clock: str | None) -> int:
    if not clock:
        return 0
    parts = clock.split(":")
    try:
        minutes = int(parts[0])
        seconds = int(parts[1]) if len(parts) == 2 else 0
    except ValueError:
        return 0
    if minutes < 0 or not 0 <= seconds < 60:
        return 0
    return minutes * 60 + seconds


def format_clock(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}"


def write_log(path: Path, entry: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=True) + "\n")


def post_period_event(
    client: ScorerClient,
    match_id: str,
    sequence: int,
    event_type: str,
    period: int,
    clock: str,
) -> dict[str, Any]:
    return client.request(
        f"/matches/{match_id}/events",
        "POST",
        {
            "client_seq": sequence,
            "type": event_type,
            "payload": {"period": period},
            "clock": clock,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic events for a local demo match."
    )
    parser.add_argument(
        "--match-id", help="Match ID from the scorer pass; prompts if multiple matches exist."
    )
    parser.add_argument(
        "--interval", type=float, default=40, help="Seconds between events (default: 40)."
    )
    parser.add_argument(
        "--count", type=int, help="Stop after this many events; default runs until interrupted."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Send events to the match; otherwise dry-run only."
    )
    parser.add_argument(
        "--start", action="store_true", help="Start an upcoming match and its first period."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("auto-score-events.jsonl"),
        help="Append accepted actions to this JSONL file (default: auto-score-events.jsonl).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        raise ValueError("--interval must be greater than zero.")
    if args.count is not None and args.count < 1:
        raise ValueError("--count must be at least 1.")

    scorer_url = os.environ.get("OURSPORT_SCORER_URL")
    if not scorer_url:
        scorer_url = getpass.getpass("Paste the scorer URL (input hidden): ")
    client = client_from_scorer_url(scorer_url)
    match = select_match(client.request("/scoring/me"), args.match_id)

    home_name = (match.get("home") or {}).get("name", "Home")
    away_name = (match.get("away") or {}).get("name", "Away")
    print(f"Selected {home_name} v {away_name} ({match['match_id']}).")
    if args.apply:
        if input("This must be a dedicated test/demo match. Type DEMO to continue: ") != "DEMO":
            raise ValueError("Confirmation did not match; no events were sent.")
    else:
        print("Dry run only: no match data will be changed. Use --apply to send events.")

    match_id = match["match_id"]
    state = client.request(f"/matches/{match_id}/scoring")
    pad = client.request(f"/sports/{state['sport']}/event-types")

    if state["data_level"] != "events":
        raise ValueError("The selected match does not accept live events.")
    if state["score"]["finished"]:
        print("Full time is already recorded; stopping without finishing the match.")
        return 0
    if state["status"] in {"scheduled", "postponed"}:
        if not args.start:
            raise ValueError("The match is not live. Use --start to begin this demo match.")
        if args.apply:
            client.request(f"/matches/{match_id}/start", "POST")
            accepted = post_period_event(
                client, match_id, state["last_client_seq"] + 1, "period_start", 1, "0:00"
            )
            write_log(
                args.log,
                {
                    "at": datetime.now(UTC).isoformat(),
                    "match_id": match_id,
                    "action": "Start period",
                    "event_type": "period_start",
                    "period": 1,
                    "clock": "0:00",
                    "accepted": accepted,
                },
            )
            state = client.request(f"/matches/{match_id}/scoring")
        else:
            print("Dry run would start the match and record period_start before the first event.")
            state["status"] = "live"
            state["period"] = 1
    elif state["status"] != "live":
        raise ValueError(f"The match cannot be scored while its status is {state['status']}.")

    if state["period"] == 0:
        if not args.start:
            raise ValueError("The match has no started period. Use --start to initialize it.")
        if args.apply:
            accepted = post_period_event(
                client, match_id, state["last_client_seq"] + 1, "period_start", 1, "0:00"
            )
            write_log(
                args.log,
                {
                    "at": datetime.now(UTC).isoformat(),
                    "match_id": match_id,
                    "action": "Start period",
                    "event_type": "period_start",
                    "period": 1,
                    "clock": "0:00",
                    "accepted": accepted,
                },
            )
            state = client.request(f"/matches/{match_id}/scoring")
        else:
            state["period"] = 1
            print("Dry run would record period_start before the first event.")

    periods = state["periods"]
    period_minutes = state["period_minutes"]
    if not isinstance(periods, int) or periods < 1:
        raise ValueError("The match has no valid configured periods.")
    if not isinstance(period_minutes, int) or period_minutes < 1:
        raise ValueError("The match has no valid configured period length.")
    period_seconds = period_minutes * 60

    if state["between_periods"]:
        if state["period"] >= periods:
            print("Full time already recorded; stopping without finishing the match.")
            return 0
        next_period = state["period"] + 1
        boundary_clock = format_clock(state["period"] * period_seconds)
        if args.apply:
            accepted = post_period_event(
                client,
                match_id,
                state["last_client_seq"] + 1,
                "period_start",
                next_period,
                boundary_clock,
            )
            write_log(
                args.log,
                {
                    "at": datetime.now(UTC).isoformat(),
                    "match_id": match_id,
                    "action": "Start period",
                    "event_type": "period_start",
                    "period": next_period,
                    "clock": boundary_clock,
                    "accepted": accepted,
                },
            )
            state = client.request(f"/matches/{match_id}/scoring")
        else:
            print(f"Would record period_start for period {next_period} at {boundary_clock}.")
            state["period"] = next_period
            state["between_periods"] = False

    current_period = state["period"]
    if not 1 <= current_period <= periods:
        raise ValueError("The match is not in a configured playable period.")
    previous_clock = next(
        (event["clock"] for event in state["events"] if event["clock"]), None
    )
    period_clock_start = (current_period - 1) * period_seconds
    elapsed_in_period = max(
        0, min(period_seconds, clock_seconds(previous_clock) - period_clock_start)
    )
    period_started_at = time.monotonic() - elapsed_in_period
    emitted = 0
    while args.count is None or emitted < args.count:
        elapsed = int(time.monotonic() - period_started_at)
        remaining = period_seconds - elapsed
        if remaining <= 0:
            boundary_clock = format_clock(current_period * period_seconds)
            if args.apply:
                state = client.request(f"/matches/{match_id}/scoring")
                sequence = state["last_client_seq"] + 1
                accepted = post_period_event(
                    client,
                    match_id,
                    sequence,
                    "period_end",
                    current_period,
                    boundary_clock,
                )
                write_log(
                    args.log,
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "match_id": match_id,
                        "action": "End period",
                        "event_type": "period_end",
                        "period": current_period,
                        "clock": boundary_clock,
                        "accepted": accepted,
                    },
                )
            else:
                print(
                    f"Would record period_end for period {current_period} at {boundary_clock}."
                )

            if current_period >= periods:
                print("Full time recorded; stopping without finishing the match.")
                break

            next_period = current_period + 1
            if args.apply:
                state = client.request(f"/matches/{match_id}/scoring")
                sequence = state["last_client_seq"] + 1
                accepted = post_period_event(
                    client,
                    match_id,
                    sequence,
                    "period_start",
                    next_period,
                    boundary_clock,
                )
                write_log(
                    args.log,
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "match_id": match_id,
                        "action": "Start period",
                        "event_type": "period_start",
                        "period": next_period,
                        "clock": boundary_clock,
                        "accepted": accepted,
                    },
                )
            else:
                print(
                    f"Would record period_start for period {next_period} at {boundary_clock}."
                )
            current_period = next_period
            period_clock_start = (current_period - 1) * period_seconds
            period_started_at = time.monotonic()
            continue

        time.sleep(min(args.interval, remaining))
        elapsed = int(time.monotonic() - period_started_at)
        if elapsed >= period_seconds:
            continue
        if args.apply:
            state = client.request(f"/matches/{match_id}/scoring")
            if state["status"] != "live" or state["between_periods"]:
                raise ValueError(
                    "The match stopped being actively scorable; automation has stopped."
                )
            sequence = state["last_client_seq"]

        button = event_button(pad, match)
        team_side = random.choice(("home", "away"))
        team_id = match[f"{team_side}_team_id"]
        body = {
            "client_seq": sequence + 1,
            "type": button["type"],
            "payload": button.get("payload") or {},
            "team_id": team_id if button["team"] else None,
            "player_id": None,
            "clock": format_clock(period_clock_start + elapsed),
        }
        label = button["label"]

        if args.apply:
            accepted = client.request(f"/matches/{match_id}/events", "POST", body)
            sequence += 1
            entry = {
                "at": datetime.now(UTC).isoformat(),
                "match_id": match_id,
                "action": label,
                "event_type": body["type"],
                "payload": body["payload"],
                "clock": body["clock"],
                "team": team_side if button["team"] else None,
                "team_id": body["team_id"],
                "client_seq": body["client_seq"],
                "live_score": accepted.get("live"),
            }
            write_log(args.log, entry)
            score = accepted.get("live") or {}
            print(
                f"Recorded {label} for {team_side} — "
                f"{score.get('home_goals', '?')}-{score.get('away_goals', '?')}"
            )
        else:
            sequence += 1
            print(
                f"Would record {label} for {team_side} at {body['clock']} "
                f"(client_seq {sequence})."
            )

        emitted += 1
        if args.count is not None and emitted >= args.count:
            break

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
