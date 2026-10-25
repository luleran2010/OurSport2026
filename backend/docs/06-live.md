# 06 — Match day and live: scoring, livecast, commentary

Match day is where OurSport must prove "no extra work for organisers" and "bragging rights for the tournament". It is also the moment of highest load (hundreds of families on one final, several pitches live at once).

## Match-day roles

| Role | How they get access | Sees |
| --- | --- | --- |
| Tournament owner / organiser | Account + `tournament_staff` | Organiser console: all pitches, delays, unscored matches, announcements, reschedule |
| Pitch scorer (volunteer) | Scans the **pitch QR** printed on the pitch sheet → scorer pass, no account needed | Only that pitch's matches today, big-button pad |
| Referee / team official (optional) | Scorer pass for one match | That match |

Scorer passes are revocable, time-limited (the tournament days), scoped to a pitch or match, and every event records `entered_by_pass_id` for the audit trail. A lost phone = revoke and print/show a new QR.

## Scorer pad (designed for one hand, weak signal)

- Home screen: "Pitch 3 — now: Tigers vs Royals (14:20)", then *Start*.
- Two huge buttons: **Goal Tigers**, **Goal Royals**. Secondary: card, penalty, half time, undo (last event).
- Player selection is optional and only offered for players the scorer is allowed to see.
- **Offline-first:** events queue on the device with `client_seq`; the server accepts them in order on reconnect.
- *Full time* → confirm the score → the next match on this pitch is shown immediately.
- **Results-only mode** for pitches without a volunteer: the organiser enters the final score from the console in two taps.

## What happens automatically (no organiser work)

| Trigger | OurSport does |
| --- | --- |
| Match started | Followers notified ("Tigers are playing now on pitch 3"); live page lights up |
| Goal | Live score to all viewers < 2 s; commentary within 15 s; live stakes and relevance updated |
| Full time | Standings, scenarios, bracket placeholders (e.g. "Winner Group A" → team), predictions for the next round, match analysis, report, share card, announcement draft ("Tigers beat Royals 2–1 and top Group A") |
| Group finished | Knockout fixtures filled; teams notified of their next opponent, pitch and time |
| Pitch running late | Console shows drift; one tap "delay 15 min" → engine reschedules → followers of affected teams notified |
| Team withdraws | Walkovers applied by rule; schedule compacted (preview, then confirm) |
| Tournament finished | Summary story, team recaps, final placements saved for next year's seeding |

## Ingestion rules (`scoring` module)

- Only a valid scorer pass for the pitch/match, tournament staff or an organisation admin may post events, and only while `matches.status = 'live'`.
- Idempotent by (`match_id`, `client_seq`): a retry returns the original `seq` with `200`.
- Events validated against the sport's event types and the current live state.
- `seq` assigned with `UPDATE matches SET last_seq = last_seq + 1 … RETURNING last_seq` in the transaction.
- Undo = new event `{type: "undo", undoes_seq}`; live state recomputed by replay.
- Out-of-order client submissions accepted in `client_seq` order; 409 with the expected next `client_seq` only if accepting would reorder already-published events.
- **Implementation (T-030):** events are validated and replayed by `engine.sports.football` (`validate_event`, `replay`, `detect_moments`, `result_of`); the match row is locked per event (`competitions.lock_match`), so concurrent retries store one event. `live_state.state` holds the score, period, shootout, sent-off players and the last moments. Pitch passes are created on `TournamentPublished`; the QR token is an HMAC of the pass id with the server secret (stored only as a hash, so pitch sheets can be reprinted). Results are stored as `{home_goals, away_goals, decided_by, home_penalties, away_penalties}`. Printable pitch sheets (QR) are a follow-up.

## Livecast: the tournament's bragging rights

| Surface | What | Access |
| --- | --- | --- |
| **Tournament live page** (`/tournaments/{id}/live`) | All pitches live now, scores, latest commentary, "next up" | Per live access policy |
| **Match page** | Score, timeline, commentary, stakes, prediction band, stream (if attached) | Per live access policy |
| **Venue big screen** (`/screen`) | Rotating now-playing / next-up / standings / announcements, QR "follow your team" | Public, read-only, no personal data |
| **Embeddable widget** | Live scores and standings for the organiser's or clubs' websites | Public |
| **Share cards** | Result, "through to the semi-final", "champions", group tables — WhatsApp/Facebook ready | Public after finish (live score cards only if policy is `public`) |
| **Live draw** | Draw revealed pot by pot on screen or stream | Public |
| **Live video** (later) | Embedded third-party stream next to live data | Per access + filming checks |

### Live access policy (per tournament, ADR 0011)

`tournaments.settings.live_access`:

- `public` — live score, timeline and commentary for everyone (default for community tournaments: maximises reach and pride).
- `members` — signed-in users who follow the tournament or are members of a participating organisation.
- `premium` — premium entitlement or event pass (ADR 0006 boundary).

Staff, scorers, admins of participating organisations and editors always have access. `can_watch_live(viewer, match)` implements the policy; only it and the live serializer change if the policy changes.

## WebSocket protocol

1. `GET /api/v1/live/token?match_id=` (or `tournament_id=`) → checks `can_watch_live` → token (JWT, 60 s, bound to viewer + match/tournament). For `public` policy, signed-out viewers get tokens too.
2. Connect `wss://<host>/api/v1/live/matches/{id}?token=…&since_seq=<last seen or 0>` or `/live/tournaments/{id}?token=…` (multiplexed: all live matches of a tournament, score-level messages only).
3. Server sends `snapshot` first, then new messages.

Envelope:

```json
{ "type": "event", "match_id": "…", "seq": 88, "version": 12,
  "server_time": "2026-10-24T14:03:11Z", "data": { } }
```

| Type | Data | When |
| --- | --- | --- |
| `snapshot` | live_state, stakes, timeline[], prediction | On connect |
| `event` | event type, team, player (if visible), score after | Every accepted event |
| `state` | live stakes, live relevance for followed teams | After `recalc_live` |
| `commentary` | text, kind, language, fact_ids, `ai_label` | After a checked commentary item |
| `stream` | the stream (`status` `live`, `paused` or `ended`) | Stream attached, paused by an opt-out, or ended (match and tournament channels) |
| `draw_step` | step, pot, group, team, total, seed (last step) | Live draw: the organiser revealed the next team (tournament channel) |
| `correction` | affected seqs, replacement items | After undo/correction |
| `schedule` | changed matches (time/pitch) | After a reschedule is confirmed |
| `announcement` | text | Organiser sends |
| `match_finished` | final result | On finish; match socket closes after 10 s |
| `ping` | — | Every 25 s |

Reliability: Redis is the fast path only; on a `seq` gap or reconnect the client calls `GET /matches/{id}/timeline?since_seq=`. Each API instance subscribes to the channels its viewers need. Idle sockets closed after 60 s without pong. Viewer counts per match in Redis (shown to organisers: "312 watching the final").

**Implementation (T-035):** `app/core/live.py` `LiveHub` (one Redis pub/sub per API instance; channels `live:match:{id}`, `live:tournament:{id}`; viewer counts `live:viewers:{id}`, shown in the organiser console). Scoring publishes `event`/`correction`/`match_finished` after commit; setup publishes `schedule` (confirmed reschedule) and `announcement` (`POST /tournaments/{id}/announcements`). Sockets live in `analysis.live`: the socket subscribes before building the snapshot and drops messages with `seq` ≤ the last sent, so reconnects with `since_seq` have no gaps or duplicates; bad tokens close with 4401; `ping` every `LIVE_PING_SECONDS` (25). `commentary` messages come from T-053; `state` messages (clock and period) are not sent yet.

## Moment detection

Done in code during ingestion via `engine.sports.<sport>.detect_moment(state, event)`. Only moments get AI commentary.

| Sport | Moments |
| --- | --- |
| **Football** (v1) | goal, equaliser, lead change, penalty awarded/scored/missed, red card, last 5 minutes with one-goal margin, comeback from 2+ down, half time, full time, shootout decided |
| Ice hockey (v2) | goal, power-play goal, empty-net situation, overtime start, shootout |
| Futsal (v1) | football's moments, plus `sixth_foul` (sixth accumulated foul of a half: direct free kicks from now on) and `timeout` |
| Floorball (next version) | goal, equaliser, lead change, penalty shot, two-minute penalty |
| Volleyball | set won, comeback set, set/match point saved |
| All | match start, period end, result, qualification decided ("Tigers are through!") |

## Commentary cadence, languages and cost control

- At most **one AI commentary item per match every 45 seconds**; moments inside the window are merged.
- With many pitches live, commentary is prioritised by audience: matches with more live viewers and knockout matches first; low-audience group matches get template lines when the budget is tight.
- Commentary is generated in the tournament's languages (e.g. fi, en, bn); one LLM call returns all languages to save latency and cost.
- **Pre-generated stakes lines** (`prepare_live_context`, built as soon as the fixture's teams are known).
- **Template fallback** for every moment type and language when the LLM is slow (> 8 s), failing, or over budget.
- Junior matches: junior tone profile; no player names unless visible.
- Every item passes the claim checker; failures are dropped and logged.
- Every item is labelled as AI-written (`ai_label`).

**Implementation (T-053):** `content/commentary.py`, run as the `write_commentary` job.
- **Trigger:** scoring defers the job for every event with moments, and at full time.
- **Cadence:** a moment within 45 s of the last line is re-deferred to the end of the window (`jobs.defer(run_at=…)`). That later line covers every event since the previous one (`seq` = the last event covered). Full time always gets its line.
- **Facts:** `analysis.service.live_fact_sheet` gives the score, the events since the last line (goals with public scorers, red cards, missed penalties), the moments, and the "if it ended now" table (`kind: commentary`).
- **Priority:** the AI writes for the `AI_SLOTS` (4) live matches of the tournament with the most live viewers, knockouts first. Other matches get template lines.
- **Fallback:** on a model error or timeout, or a checker failure, a template line is used for every language (`author_type: "template"`, no AI label), and the reason is stored.
- **Delivery:** each line is published as a `commentary` message on the match and tournament channels. Its `data` is the `CommentaryOut` (`items` per language with `fact_ids`, `author_type`, `ai_labels`, `moments`, `seq`). `GET /matches/{id}/commentary` lists the lines (live access policy while live).
- **Not built:** pre-generated stakes lines (`prepare_live_context`). The "if it ended now" fact covers the stakes.

## Non-access users during a live match

When the policy is `members` or `premium`, non-access viewers see the match is live and the teams, no score; after finish everything is public. With `public` there is no gate.

## Live video (later phase, `media` module)

- No self-hosted video. Organisers stream with a phone to a provider (YouTube Live, Mux, Cloudflare Stream or similar) and attach the playback URL.
- `POST /matches/{id}/stream` runs the **filming check** (see `13-compliance-finland.md`): organiser confirms the streaming rights for the event and venue; filming notice published; for junior teams, `filming` consent for every listed player (or the tournament's offline-consent attestation); no open opt-outs affecting the match.
- Event timestamps + stream start time → offsets for auto-highlights later.

**Venue screen (T-063):** `GET /tournaments/{id}/screen/rotation` builds panels from read models (`now_playing` 15 s, `commentary` 10 s, `next_up` 10 s, one `standings` panel per group 12 s, `announcement` 10 s for those sent in the last 30 minutes, `story` 10 s). AI text carries its labels. The screen polls it every few seconds (5 s cache) and listens to the tournament socket.

**Implementation (T-062):** the `media` module (see docs/05, Media).
- **Filming check:** filming policy not `not_allowed`; rights and venue permission confirmed; filming notice published.
  - Filming consent is needed for every junior player, and for every player when the policy is `consent_required` or the tournament is junior, unless the organiser attested offline consents.
  - No open opt-out may affect the team.
- **Opt-outs:** a new opt-out pauses live streams of the team's matches (`stream` message).
- **Live draw:** steps go pot by pot; the seed appears when the last team is drawn.
