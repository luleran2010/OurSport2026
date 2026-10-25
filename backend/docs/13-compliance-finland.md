# 13 — Compliance: GDPR, Finnish law, media and minors

OurSport operates in Finland and serves community tournaments with adults and children. This document turns the relevant rules into product requirements. **It is engineering guidance, not legal advice.** Items marked **⚖ needs legal review** must be confirmed by a lawyer (or the Finnish Data Protection Ombudsman's guidance) before launch.

## 1. Who is responsible for what

| Data | Controller | OurSport's role | Product consequence |
| --- | --- | --- | --- |
| Teams, players, team contacts, consents uploaded by the host | Hosting organisation (e.g. the FinBangla association) | Processor (GDPR Art. 28) | Processing agreement accepted before first setup (`processing_agreements`); organiser can export and delete their tournament data |
| Fan accounts, follows, notifications | OurSport | Controller | Privacy notice, export/delete, retention |
| Match events and results | Hosting organisation | Processor | Organiser controls corrections and deletion |
| AI-generated text about matches | OurSport (publisher of the text) | Controller / publisher | Labelling, claim checker, corrections, notice-and-action |

## 2. GDPR and the Finnish Data Protection Act (1050/2018)

| Requirement | Product implementation |
| --- | --- |
| Lawful basis | Contract (accounts, scoring), legitimate interest (publishing results and standings of an organised competition, team-level coverage), consent (junior profiles beyond team level, filming of minors, marketing, non-essential cookies) |
| Child's consent age for information society services in Finland: **13** | Accounts only for users aged 13+ (self-declared at signup); children under 13 are never account holders; guardians act for them |
| Data minimisation | Birth year only; contact details staff-only; redaction before LLM; no junior photos by default |
| Transparency (Art. 13/14) | Privacy notice in fi/en/bn; venue **filming notice** with QR; "Why do I see this?" on predictions and stories |
| Rights | Export/delete endpoints; organiser tools for participant data requests; respond within one month |
| Security & breaches | Encryption in transit and at rest; audit log; breach procedure: notify the **Data Protection Ombudsman (Tietosuojavaltuutettu)** within 72 h where required; runbook in `docs/runbooks/` |
| Processors & transfers | EU/EEA hosting; DPAs with cloud, email, LLM and stream providers; LLM provider configured to not retain or train on inputs; no transfer outside the EEA without SCCs ⚖ |
| Records of processing | Maintained in `docs/privacy/` |
| Publishing results of named adults | Legitimate interest for team results and public adult players; individual adult players can request `hidden` ⚖ |

## 3. Minors (under 18)

| Rule | Implementation |
| --- | --- |
| Junior players hidden by default | `visibility = hidden` for under 18 |
| Named profiles / stats require guardian consent | Consent scopes `profile`, `stats`; for 15–17-year-olds also record the young person's own agreement (good practice in Finnish youth sport) ⚖ |
| No criticism of children | Junior tone profile + banned words in claim checker |
| No predictions as percentages for the youngest | `show_probabilities = false` default for U12 and younger |
| Filming and publishing images of minors | Guardian consent (`filming`) per player, or the organiser attests that consent was collected offline (signed forms) — stored with the attestation text, who, when ⚖ |
| Opt-out at any time | `filming_optouts`; blocks stream attach for affected matches until resolved; regenerates content that named the player |

## 4. Filming and live streaming in Finland

| Topic | Rule of thumb | Product implementation |
| --- | --- | --- |
| Filming at a public sports event | Filming in public places is generally allowed in Finland, but **publishing** footage of identifiable people is personal data processing (GDPR) and can engage privacy protection (Criminal Code ch. 24, dissemination of information violating personal privacy) | Filming notice at the venue; opt-out route; junior consent check; no close-ups policy text in organiser guidance ⚖ |
| Who may stream the event | No general licence is needed to stream on the internet (broadcast licences concern radio/TV frequencies), but the **organiser must hold the rights**: venue owner's permission (city-owned fields may have their own rules) and, for federation-sanctioned competitions, the federation's media rules | `POST /stream` requires `rights_confirmed` by the organiser with a checklist (venue permission, federation rules if applicable); stored with who/when ⚖ |
| Music in streams | Background music in a stream may need licences (Teosto, Gramex) | Organiser guidance: mute PA music in streams; stream providers' music detection may block; no music added by OurSport |
| Information to participants | Teams and spectators must be informed that matches are filmed/streamed | Auto-generated **filming notice** (fi/en/bn, QR to privacy notice and opt-out) in printables; included in team schedule emails |
| Retention of recordings | Stream recordings are held by the provider | Organiser chooses "live only" or "keep replay"; replay deletion on opt-out/request |

## 5. AI-specific rules

| Rule | Implementation |
| --- | --- |
| **EU AI Act Art. 50** transparency (obligations apply from 2 Aug 2026): AI-generated text published to inform the public must be disclosed unless under human editorial responsibility ⚖ | Every AI item carries `author_type = "ai"` and a visible `ai_label`, also on share cards ("AI-written") and the venue screen |
| No automated decisions with legal or similarly significant effects on individuals | Setup decisions (groups, schedule) are about teams, computed by deterministic rules and **published by the organiser**; draw seed and reasons public for transparency |
| No personal data to the LLM beyond what is needed | Redaction + gateway guard; visible player names only for public players |
| Prompt injection via uploads | Extraction treats uploads as data; suspicious instructions flagged |

## 6. Other Finnish/EU rules touching the product

| Rule | Implementation |
| --- | --- |
| **Cookies** — Act on Electronic Communications Services (917/2014) §205 and Traficom guidance: consent for non-essential cookies/storage | Only essential cookies by default (session, CSRF); analytics only after consent; consent banner in fi/en/bn |
| **Electronic direct marketing** (same Act, §200): opt-in for natural persons | Marketing emails opt-in; transactional emails (login, schedule, match notifications the user asked for) separate |
| **Digital Services Act** — notice-and-action applies to all hosting services | Report button on stories and manual news; editor queue; statement of reasons on removal; contact point published |
| **Accessibility** — European Accessibility Act as implemented in Finland (from 28 June 2025) applies to certain consumer services (e.g. e-commerce for premium); micro-enterprises are exempt ⚖ | Target WCAG 2.1 AA for fan and scorer UIs regardless; accessibility statement |
| **Consumer protection** (selling premium/event passes to consumers) | Clear prices incl. VAT, 14-day withdrawal information where applicable, terms in Finnish ⚖ |
| **No gambling** — Finnish Lotteries Act and the gambling reform | No odds, no betting language, no betting partners (golden rule 11) |
| **Equality and non-discrimination** | No content or feature based on players' origin, religion or similar; the setup catalogue separates teams only by sporting criteria and organisation |

## 7. Compliance checks built into flows

| Flow | Check | Blocks |
| --- | --- | --- |
| First setup | Processing agreement accepted | Upload |
| Publish setup | Filming policy chosen (`no_filming`, `consented_only`, `offline_attested`); junior settings applied | Publish |
| Add players | Age → visibility default; consent required for upgrades | Visibility change |
| Attach stream | Rights confirmed; notice published; junior consents or attestation; no open opt-outs | Stream attach (409 `filming_not_permitted` with failing checks) |
| Generate content | Visibility filter; junior tone; claim checker; AI label | Publish |
| Account signup | Age 13+ confirmation; privacy notice acknowledgement | Account creation |

**Implementation (T-061):**
- **Processing terms:** uploads and extraction need the organisation's acceptance of the current terms (`PROCESSING_TERMS_VERSION`). Otherwise 409 `processing_agreement_required`; accept with `POST /organisations/{id}/processing-agreement`.
- **Filming policy:** publishing needs an explicit choice (`publishSetup` body `{filming_policy}`, stored with `settings.filming_confirmed`). Without it, 409 `setup_not_ready`. Junior tournaments may only choose `consent_required` or `not_allowed`. Policy values in the API are `allowed`, `notice`, `consent_required` and `not_allowed` (`no_filming` ≈ `not_allowed`, `consented_only` / `offline_attested` ≈ `consent_required`; the attestation itself comes with media, T-062).
- **Consent preferences:** members' `preferences` (`analytics_cookies`, `marketing_emails`, both off by default, `updated_at`) on `GET/PATCH /me`. Anonymous visitors' cookie choice stays in the browser; only essential cookies are set by the API.
- **Legal pages:** `GET /legal/{privacy|cookies|accessibility|ai|contact}?lang=fi|en|bn`, served as Markdown drafts with `needs_legal_review: true` ⚖.
- **Notice and action (DSA):** reports carry a `kind` (`mistake`, `privacy`, `illegal`, `other`). Unpublishing needs a `reason` (statement of reasons). It closes the story's open reports with that reason, and reporters see the outcome in `GET /me/reports`.
- **Rosters:** organiser endpoints to list a team's players with consents, add players (under-18s start hidden), change visibility (juniors need consents), record and withdraw consents, and link a guardian's account by email.
- **Lower visibility:** when a consent withdrawal or a visibility change makes a player less visible, `refresh_team_content` rewrites the team's stories from the new facts. It then replaces every name that is now private in the tournament's stories, commentary and announcements with "a player" / "pelaaja" / "একজন খেলোয়াড়".

## 8. Open legal questions ⚖

1. Exact consent model for 15–17-year-olds (guardian, player or both) for profiles and filming.
2. Whether publishing named adult players' goals in a community tournament can rest on legitimate interest alone.
3. Whether AI Act Art. 50 disclosure applies to sports coverage in our setting (we label regardless).
4. Federation media rules if a tournament is sanctioned by the Football Association of Finland (Palloliitto) or a district.
5. Whether we are a micro-enterprise for accessibility-law purposes at launch.
6. Data transfer terms of the chosen LLM and stream providers.
