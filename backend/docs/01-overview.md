# 01 — Product overview

## The idea in one paragraph

Local sport — community tournaments, diaspora cups, junior leagues, school tournaments — gets almost no coverage, and running it is hard work: rules in a PDF, teams in a WhatsApp thread, groups drawn on paper, schedules in a spreadsheet, results shouted across the field. **OurSport** removes that work and adds the coverage. The organiser uploads the rules and the team list; OurSport sets up the entire tournament automatically (groups drawn according to the rules, fair seeding, schedule over pitches and days). On match day the organising team taps scores into their phones; OurSport turns every tap into a live scoreboard, standings, "what does my team need", predictions with reasons, AI commentary, match analysis and stories — so that a three-day community cup is followed like a professional league by the people who care: families, friends, the community, relatives abroad.

The name matters: **OurSport**. The experience is built around *your* team and *your* league, so it feels personal, while every other match stays one tap away.

## Reference customer: a FinBangla community football cup

| Fact | Consequence for the product |
| --- | --- |
| 3 days, many matches per day, several pitches at once | Setup must be finished well before day 1; the schedule must respect pitches, rest times and days; scoring happens on several pitches in parallel |
| Teams are community, club and friend teams; some return every year | Seeding can use last year's results ("last year's semi-finalists in different groups") |
| Rules exist as a document written by the hosts, sometimes incomplete | AI extracts the rules; where the rules are silent, OurSport applies a fair, internationally used default and says so |
| Volunteer organising team | No training needed; one big-button screen per pitch; no extra work compared to paper |
| Audience in Finland and Bangladesh, three languages (fi, en, bn) | Multilingual content; times in the viewer's time zone; light pages for weak connections |
| Mixed adult and junior matches | Junior protections and Finnish compliance always on (see `13-compliance-finland.md`) |

## Who uses it and how

| User | Typical moment | What they want |
| --- | --- | --- |
| **Organiser (host)** | Two weeks before the cup | Upload rules + team list, answer at most a few questions, tap *Publish*. Share one link with all teams |
| **Organising team member / pitch scorer** | At pitch 3, phone in one hand | Scan the pitch QR, tap "goal — home", done. Works with weak signal |
| **Organiser on match day** | At the HQ tent | See all pitches at a glance, matches running late, unscored results; shift the schedule with one tap; announce results |
| Supporter / family member | Saturday, waiting for their team's next game | "When do we play, where, what do we need, how did we do, how strong is the next opponent" — in their language |
| Relative abroad | Evening in Dhaka | Live score and commentary in Bengali, times in local time |
| Player | After the match | The match analysis and their team's journey through the tournament; share cards |
| Club / association admin | Before the season | Members, premium seats, teams, consents |
| Editor | Busy weekends | Review flagged AI content, correct |

### Usage pattern (drives many design choices)

- **Bursty.** Near zero on most days; peaks on tournament days, often hundreds of viewers on one final.
- **Short and intense.** A 3-day cup has no "evening before" for every round: the next round's preview, scenarios and predictions must be built within minutes of the previous result.
- **Infrequent.** A supporter may open the app only around tournaments. Re-engagement comes from the organiser's share link, WhatsApp share cards, notifications and next year's edition.
- **Emotional, family audience.** Clear explanations, gentle tone for junior teams, strict protection of children's data.

## What the app delivers

**For organisers**

1. **Automatic setup:** upload rules (PDF, Word, text, photo, link) and the team list (Excel, CSV, pasted text, photo) → full tournament: rules, groups drawn by the rules' seeding instructions, schedule across days and pitches, knockout bracket. See `12-tournament-setup.md`.
2. **Match-day console:** per-pitch scorer passes (QR, no account needed), big-button scoring, results-only mode, automatic standings and bracket progression, "running late" rescheduling, announcements.
3. **Livecast pride:** a public tournament page, venue big-screen mode, embeddable widget, share cards, optional live video with consent checks.

**For supporters**

4. **My Team hub:** next match, what we need, chances with reasons, form, journey through the tournament, history across editions. See `14-personal-experience.md`.
5. **Standings, scenarios, predictions, comparisons, match analysis** for every match, however small the tournament.
6. **Live:** score, timeline, AI commentary, live stakes ("if it ends like this…"), "other matches that matter to us".
7. **Stories:** previews, reports, tournament summary — written by AI from facts, checked before publishing, labelled as AI.

## Sport priority

| Order | Sport | Why |
| --- | --- | --- |
| 1 | **Football** (11-a-side, 7-a-side, 5-a-side; community, junior, school) | Largest number of players and teams; the FinBangla cup and most community tournaments |
| 2 | **Futsal** (in this release with football) | Same goal-based engine logic with small rule differences (accumulated fouls, timeouts); popular indoor format for community and winter tournaments |
| 3 | Ice hockey (next version) | Second-largest junior sport in Finland; Liiga sample data for testing the engine |
| 4 | Floorball (next version) | Goal-based like futsal |
| 5 | Volleyball | Set-based scoring |
| Later | Cricket and other community sports | On demand from communities (cricket is a strong candidate for the Bangladeshi community) |

## Principles

1. **Numbers from code, words from AI.** The engine calculates; the LLM explains; a checker verifies.
2. **AI proposes, engine decides, organiser publishes.** Setup is automatic but never unaccountable: every assumption is shown, the draw is reproducible from its seed, nothing is public before *Publish*.
3. **No extra work for organisers.** Every feature must remove a task the organiser already does (paper scoresheet, spreadsheet, WhatsApp announcements), never add one.
4. **Personal first, complete always.** Lead with the viewer's team; never hide the rest of the tournament.
5. **Compute on write, serve on read.** Fans never wait for a calculation.
6. **Events are the truth.** Append-only match events; everything else rebuildable.
7. **Honest uncertainty.** Predictions are ranges with confidence; no percentages when data is too thin.
8. **Kind to kids, lawful by default.** Team-focused language for junior matches; no exposure of hidden players; Finnish and EU rules built in, not bolted on.
9. **Simple to run.** One codebase, one image, PostgreSQL + Redis. Boring, well-known tools.

## Glossary

| Term | Meaning |
| --- | --- |
| Organisation | The club, association or school that owns teams or hosts tournaments (e.g. the FinBangla association) |
| Tournament series / edition | A recurring tournament ("FinBangla Cup") and one year of it ("2026"). Previous editions feed seeding |
| Tournament | One competition: league season, cup, weekend tournament. Has groups, fixtures, rules |
| Setup session | One run of the automatic setup: uploads → extraction → draft → draw → schedule → publish |
| Rule config | Structured, versioned rules (points, tiebreakers, format, advancement), confirmed on publish |
| Format spec | Number and size of groups, who advances, knockout bracket shape, third-place match |
| Seeding policy | How teams are ranked into pots and which teams must be kept apart in the draw |
| Draw | The engine's assignment of teams to groups, reproducible from its stored seed |
| Schedule plan | The engine's assignment of matches to days, pitches and times |
| Assumption | A setup choice the rules did not specify, filled from the standard policy catalogue and shown to the organiser |
| Open question | Something the AI could not decide safely; the organiser answers it before publishing |
| Scorer pass | A revocable, pitch- or match-scoped scoring permission opened by scanning a QR code |
| Match event | One thing that happened in a match (goal, card, period end). Append-only, with a per-match `seq` |
| Data level | `results` (only final scores) or `events` (live events entered by a scorer) |
| Read model / snapshot | Precomputed, versioned table served to the front end |
| Fact sheet | List of verified facts that the LLM may use for one piece of content |
| Claim checker | Code that verifies every number/name/status in AI text against the fact sheet |
| Rating | Team strength number used for predictions (Elo-based) |
| Live access policy | Per tournament: who may see live score and commentary (`public`, `members`, `premium`) |
| Visibility | Player privacy level: `public`, `family_only`, `hidden` |
| Moment | A live event worth commentary (goal, equaliser, lead change, red card, late winner) |
| Relevance | How much another match affects the viewer's team's chances ("matches that matter to us") |
