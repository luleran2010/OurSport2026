// Maps the OurSport API v1 (snake_case, UUIDs, ISO 8601 UTC) to the shapes the screens use
// (camelCase, epoch ms, `score: [home, away]`, teams with `short` and `color`).
// The API is the contract; this file is the only place that knows both shapes.

export const ms = (iso) => (iso ? Date.parse(iso.length === 10 ? `${iso}T00:00:00` : iso) : null)

// ---- reference data (filled by the catalogue, used to dress up ids) -----------------------

export const ref = { teams: {}, clubs: {}, tournaments: {}, orgs: {}, matches: [] }

const SPORT_ICON = { football: '⚽', futsal: '🥅', ice_hockey: '🏒', floorball: '🥍', basketball: '🏀', volleyball: '🏐', cricket: '🏏' }
const AGE_LABEL = { adult: 'Adult', senior: 'Senior' }
const PALETTE = ['#e4572e', '#2e86ab', '#3bb273', '#e0a100', '#7768ae', '#0f7173', '#d7263d', '#f46036', '#1b998b', '#c5283d']

export const ageLabel = (a) => AGE_LABEL[a] ?? (a ? a.toUpperCase() : '')

function colorOf(id) {
  let h = 0
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

function initials(name) {
  const words = name.split(/[\s\-·]+/).filter(Boolean)
  return (words.length > 1 ? words.map((w) => w[0]).join('') : name).slice(0, 3).toUpperCase()
}

export function sport(s) {
  return { id: s.code, label: s.name, icon: SPORT_ICON[s.code] ?? '🏅' }
}

export function club(o, teamIds = []) {
  const color = o.colors?.primary ?? colorOf(o.id)
  return {
    id: o.id, slug: o.slug, name: o.name, short: initials(o.name), color, city: o.town ?? '', region: o.town ?? '',
    sports: o.sports, teamIds, venue: '', lat: null, lon: null, logoUrl: o.logo_url ?? null,
    sponsors: (o.sponsors ?? []).map((s) => ({ ...s, logoUrl: s.logo_url ?? s.logoUrl ?? null, showOn: s.show_on ?? s.showOn })),
    contactEmail: null, secondaryColor: o.colors?.secondary ?? '#ffffff', description: '',
  }
}

/** A team from a list item or a bare `{id, name, short_name}` (TeamName). */
export function team(t) {
  if (!t) return null
  const known = ref.teams[t.id]
  if (known) return known
  const org = ref.orgs[t.organisation_id]
  const where = (t.tournament_ids ?? []).map((id) => ref.tournaments[id]).filter(Boolean)
  return {
    id: t.id, name: t.name, short: t.short_name || initials(t.name), color: org?.colors?.primary ?? colorOf(t.id),
    sport: t.sports?.[0] ?? where[0]?.sport ?? '', league: where[0]?.name ?? '', clubId: t.organisation_id ?? null,
    region: org?.town ?? '', ageGroup: t.age_group ?? 'adult',
  }
}

export const placeholder = (source, code, side) => ({
  id: `tbd:${code}:${side}`, name: source ?? 'To be decided', short: 'TBD', color: '#6b7280', sport: '', league: '',
  clubId: null, region: '', ageGroup: '',
})

export function tournamentSummary(t) {
  return {
    id: t.id, name: t.name, sport: t.sport, startsAt: ms(t.starts_on), endsAt: ms(t.ends_on),
    organiser: { name: t.organisation_name ?? '', clubId: t.organisation_id }, venue: '', region: '',
    format: '', resultsOnly: false, junior: t.is_junior, status: t.status, groups: [], teams: [],
  }
}

// ---- matches ---------------------------------------------------------------------------------

const STATUS = { scheduled: 'upcoming', postponed: 'upcoming', live: 'live', finished: 'finished', walkover: 'finished', cancelled: 'finished' }
const STAGE = { group: 'Group', round_of_16: 'Round of 16', quarter_final: 'Quarter-final', semi_final: 'Semi-final', third_place: 'Third place', final: 'Final' }
const PERIOD = { 1: '1st half', 2: '2nd half', 3: 'Extra time', 4: 'Extra time' }

export function match(m) {
  const status = STATUS[m.status] ?? 'upcoming'
  const startsAt = ms(m.starts_at)
  return {
    id: m.id, code: m.code, sport: m.sport, league: ref.tournaments[m.tournament_id]?.name ?? '', status,
    home: team(m.home) ?? placeholder(m.home_source, m.code, 'h'),
    away: team(m.away) ?? placeholder(m.away_source, m.code, 'a'),
    // The live access policy can hide a live score (`score: null`): shown as "–", never a number.
    venue: m.pitch ?? '', score: m.score ? [m.score.home_goals, m.score.away_goals] : status === 'upcoming' ? null : ['–', '–'],
    scoreHidden: !m.score && status !== 'upcoming',
    clock: null, period: m.score?.period ? PERIOD[m.score.period] ?? null : null, viewers: null, lastEvent: null, flash: null,
    startsAt, endedAt: status === 'finished' ? startsAt : null, tournamentId: m.tournament_id,
    stage: m.group ?? STAGE[m.stage] ?? m.stage, correction: null,
    dataLevel: m.data_level === 'results' ? 'results_only' : 'live',
  }
}

// ---- stories ---------------------------------------------------------------------------------

export const TAG = { preview: 'Preview', report: 'Match report', team_recap: 'Team recap', summary: 'Summary', news: 'News' }

/** v1 stores one row per language; the screens show one story with its languages. */
export function story(s, languages = [s.language]) {
  const paragraphs = s.body.split(/\n\n+/).map((paragraph) => paragraph.trim()).filter(Boolean)
  const summary = paragraphs.length > 1 ? paragraphs[0] : ''
  const body = paragraphs.length > 1 ? paragraphs.slice(1) : paragraphs
  return {
    id: s.id, tournamentId: s.tournament_id, matchId: s.subject_type === 'match' ? s.subject_id : null,
    clubId: s.subject_type === 'organisation' ? s.subject_id : null, teamIds: s.subject_type === 'team' ? [s.subject_id] : [],
    title: s.headline, summary, body, tag: TAG[s.kind] ?? s.kind,
    author: s.author_type === 'ai' ? 'OurSport AI' : 'Editor', authorType: s.author_type === 'ai' ? 'ai' : 'editor',
    aiLabel: s.ai_label, publishedAt: ms(s.published_at), language: s.language, availableLanguages: languages,
    facts: [], imageUrl: null, relatedMatchIds: [], correctedAt: ms(s.corrected_at), correctionNote: null,
  }
}

/** One story per subject and kind, in the preferred language (else English, else any). */
export function storiesIn(rows, lang = 'en') {
  const bySubject = new Map()
  for (const s of rows) {
    const key = `${s.subject_type}:${s.subject_id}:${s.kind}`
    bySubject.set(key, [...(bySubject.get(key) ?? []), s])
  }
  return [...bySubject.values()].map((group) => {
    const pick = group.find((s) => s.language === lang) ?? group.find((s) => s.language === 'en') ?? group[0]
    return story(pick, group.map((s) => s.language))
  })
}

// ---- standings and scenarios -----------------------------------------------------------------

const TIEBREAK = { label: 'GD', description: 'Goal difference' }

const FORMAT_TEXT = {
  round_robin: () => 'One table: everyone plays everyone once.',
  double_round_robin: () => 'One table: everyone plays everyone twice.',
  groups_then_knockout: (groups) => `${groups} group${groups === 1 ? '' : 's'}, then knockout.`,
  knockout: () => 'Knockout.',
}

/** TournamentPage.format (null until the rules are confirmed) as the fan pages show it. */
export function format(f, groupCount) {
  return {
    format: f ? FORMAT_TEXT[f.kind]?.(groupCount) ?? '' : '',
    qualifyCount: f?.qualify_per_group ?? 0, // 0: no knockout follows, the table decides
    bestOfRest: f?.best_of_rest ?? 0,
    qualifyLabel: f?.kind === 'groups_then_knockout' ? 'the knockout stage' : '',
    pointsWin: f?.points.win ?? 3, pointsDraw: f?.points.draw ?? 1, matchMinutes: f?.match_minutes ?? null,
  }
}

export function standings(page, { qualifyCount = 0, bestOfRest = 0 } = {}) {
  return {
    updatedAt: Date.now(), tiebreak: TIEBREAK, forLabel: 'GF', againstLabel: 'GA', qualifyCount, bestOfRest,
    groups: page.groups.map((g) => ({
      id: g.group_id ?? g.group, name: g.group || 'Table',
      rows: g.rows.map((r) => ({
        position: r.position, team: team(r.team), played: r.played, won: r.won, drawn: r.drawn, lost: r.lost,
        scored: r.goals_for, conceded: r.goals_against, tiebreakValue: r.goal_difference,
        tiebreakDisplay: r.goal_difference > 0 ? `+${r.goal_difference}` : String(r.goal_difference),
        points: r.points, form: r.form.slice(-3), status: r.status ?? 'alive',
      })),
    })),
    topScorers: null,
  }
}

const CARD_STATUS = { clinched: 'through', eliminated: 'out' }
const HEADLINE = { through: 'Through', out: 'Out', alive: 'Still in it' }

/** A scenario card from the scenario read model, the team's table row and its remaining games. */
export function scenarioCard(page, table, matches) {
  const status = CARD_STATUS[page.scenario.status] ?? 'alive'
  const group = table?.groups.find((g) => g.rows.some((r) => r.team.id === page.team.id))
  const row = group?.rows.find((r) => r.team.id === page.team.id)
  const remaining = matches
    .filter((m) => m.status !== 'finished' && (m.home.id === page.team.id || m.away.id === page.team.id))
    .map((m) => ({ matchId: m.id, opponent: m.home.id === page.team.id ? m.away : m.home, status: m.status, startsAt: m.startsAt }))
  const paths = page.scenario.paths ?? []
  return {
    team: team(page.team), groupId: group?.id ?? '', groupName: group?.name ?? '', position: row?.position ?? 0,
    points: row?.points ?? 0, maxPoints: (row?.points ?? 0) + 3 * remaining.length, status,
    headline: paths[0]?.result || HEADLINE[status], detail: paths.map((p) => p.summary).filter(Boolean).join(' '),
    remaining,
  }
}

// ---- timeline ----------------------------------------------------------------------------------

const KIND = { goal: 'goal', period_start: 'kickoff', period_end: 'period', undo: 'correction' }
const EVENT_WORDS = {
  goal: 'Goal!', yellow_card: 'Yellow card', second_yellow: 'Second yellow card', red_card: 'Red card',
  substitution: 'Substitution', penalty_missed: 'Penalty missed', shootout_kick: 'Shootout kick', foul: 'Foul',
  timeout: 'Timeout', period_start: 'Period under way', period_end: 'End of the period', undo: 'Correction',
}

export function timeline(events, commentary, m) {
  const teamName = (id) => (id === m.home.id ? m.home.name : id === m.away.id ? m.away.name : '')
  const minute = (clock) => (clock ? parseInt(clock, 10) || 0 : 0)
  const rows = events
    .filter((e) => !e.undone)
    .map((e) => ({
      id: `ev-${e.seq}`, minute: minute(e.clock), kind: KIND[e.type] ?? 'event', ai: false, at: e.seq,
      team_id: e.team_id, text: e.payload?.text ?? [EVENT_WORDS[e.type] ?? e.type, teamName(e.team_id)].filter(Boolean).join(' — '),
    }))
  const lines = commentary.map((c) => ({
    id: `cm-${c.id}`, minute: 0, kind: 'insight', ai: c.author_type === 'ai', at: ms(c.created_at),
    text: (c.items.find((i) => i.language === 'en') ?? c.items[0])?.text ?? '',
  }))
  return [...rows, ...lines]
}

// ---- me ------------------------------------------------------------------------------------

export const GUEST = {
  signedIn: false, name: 'Guest fan', email: null, language: 'en', timeZone: null, premium: null,
  follows: { clubs: [], teams: [], tournaments: [] }, family: [], roles: [], followIds: {}, unread: 0,
}

const KIND_OF = { organisation: 'clubs', team: 'teams', tournament: 'tournaments' }

/** `Me` as the screens know it. */
export function me(m, family = [], hasPass = false) {
  const follows = { clubs: [], teams: [], tournaments: [] }
  const followIds = {}
  for (const f of m.follows) {
    const key = KIND_OF[f.target_type]
    if (!key) continue
    follows[key].push(f.target_id)
    followIds[`${f.target_type}:${f.target_id}`] = f.id
  }
  const roles = []
  const organiser = m.staff_tournaments.some((s) => s.role === 'owner' || s.role === 'organiser')
  if (organiser) roles.push({ clubId: '*', clubName: 'OurSport', role: 'publisher', label: 'Publisher' })
  if (organiser || hasPass) roles.push({ clubId: '*', clubName: 'OurSport', role: 'scorer', label: 'Scorer' })
  if (m.global_roles.includes('editor')) roles.push({ clubId: '*', clubName: 'OurSport', role: 'editor', label: 'Editor' })
  const plan = m.plan && m.plan.tier !== 'free' ? m.plan : null
  const via = plan?.granted_by_organisation_id
  return {
    signedIn: true, id: m.id, name: m.display_name, email: m.email, language: m.language, timeZone: m.time_zone,
    premium: plan ? { plan: plan.tier === 'premium' ? 'Premium' : plan.tier, viaClubId: via, viaClubName: ref.orgs[via]?.name ?? '',
      validUntil: ms(plan.valid_until) } : null,
    follows, followIds, family, roles, unread: m.unread_notifications, staffTournaments: m.staff_tournaments,
  }
}

export function followItem(f) {
  const kind = { organisation: 'club', team: 'team', tournament: 'tournament' }[f.target_type] ?? f.target_type
  const t = f.target ?? { name: '' }
  const known = kind === 'team' ? ref.teams[f.target_id] : kind === 'club' ? ref.clubs[f.target_id] : null
  return {
    id: f.id, kind, targetId: f.target_id, name: t.name, subtitle: t.subtitle ?? '', short: t.short_name ?? initials(t.name || '?'),
    color: known?.color ?? colorOf(f.target_id), sport: t.sport ?? null, startsAt: ms(t.starts_on), endsAt: ms(t.ends_on),
    notifications: {
      matchStart: f.notify.match_start ?? true, liveUpdates: f.notify.goal ?? true, results: f.notify.result ?? true,
      scenarioChanges: f.notify.scenario_change ?? true, news: f.notify.news ?? true,
    },
  }
}

export const NOTIFY_FIELD = { matchStart: 'match_start', liveUpdates: 'goal', results: 'result', scenarioChanges: 'scenario_change', news: 'news' }

const NOTICE_KIND = { goal: 'live_update', match_start: 'match_start', result: 'result', scenario_change: 'scenario_change', relevance: 'scenario_change' }

export function notification(n) {
  const [title, ...rest] = n.text.split(' — ')
  const link = n.match_id ? { type: 'match', id: n.match_id } : n.tournament_id ? { type: 'event', id: n.tournament_id }
    : n.team_id ? { type: 'team', id: n.team_id } : null
  return { id: n.id, kind: NOTICE_KIND[n.kind] ?? 'news', title, body: rest.join(' — '), at: ms(n.created_at), read: n.read, link }
}
