// The app's API. Fan pages, sign-in, follows, notifications and the scorer area use the OurSport
// API v1 (backend/docs/05-api.md; the real backend and mock_backend serve the same contract) and
// adapt its responses to the shapes the screens use (adapt.js). Publisher operations still use
// legacy routes until that area moves to v1.
import * as A from './adapt'
import { editorDesk } from './editor'
import { API_BASE, hasSession, legacy, qs, scorerPass, setScorerPass, v1, v1All } from './http'

export { API_BASE }
const id = encodeURIComponent

// ---- catalogue (loaded once; dresses up the ids in every other response) --------------------

let catalog = null

function organisationId(value) {
  const organisation = A.ref.orgs[value] ?? Object.values(A.ref.orgs).find((item) => item.slug === value)
  return organisation?.id ?? value
}

function loadCatalog() {
  catalog ??= Promise.all([v1('/sports'), v1All('/organisations'), v1All('/tournaments'), v1All('/teams')])
    .then(([sports, orgs, tournaments, teams]) => {
      for (const o of orgs) A.ref.orgs[o.id] = o
      for (const t of tournaments) A.ref.tournaments[t.id] = t
      const list = teams.map((t) => A.team(t))
      for (const t of list) A.ref.teams[t.id] = t
      const clubs = orgs.map((o) => A.club(o, list.filter((t) => t.clubId === o.id).map((t) => t.id)))
      for (const c of clubs) A.ref.clubs[c.id] = c
      return { sports, orgs, tournaments, teams: list, clubs }
    })
    .catch((err) => {
      catalog = null
      throw err
    })
  return catalog
}

const SEARCH_TYPES = [
  { id: 'all', label: 'All' }, { id: 'clubs', label: 'Clubs' }, { id: 'teams', label: 'Teams' },
  { id: 'events', label: 'Events' }, { id: 'players', label: 'Players' },
]

// ---- me --------------------------------------------------------------------------------------

async function family(ids) {
  const rows = await Promise.all(ids.map((pid) => v1(`/players/${id(pid)}`).catch(() => null)))
  return rows.filter(Boolean).map((p) => ({
    player: { id: p.id, name: p.display_name, number: p.shirt_number, position: '', team: A.team(p.team) },
    relation: 'guardian',
  }))
}

let lastMe = A.GUEST

async function me() {
  if (!hasSession()) return (lastMe = { ...A.GUEST, roles: scorerRoles() })
  try {
    await loadCatalog().catch(() => {})
    const m = await v1('/me')
    lastMe = A.me(m, await family(m.family_player_ids), Boolean(scorerPass()))
  } catch (err) {
    if (err.status !== 401) throw err
    lastMe = { ...A.GUEST, roles: scorerRoles() }
  }
  return lastMe
}

/** A scorer pass on this device opens the scorer area without an account. */
const scorerRoles = () => (scorerPass() ? [{ clubId: '*', clubName: 'OurSport', role: 'scorer', label: 'Scorer' }] : [])

// the screens' follow kinds -> v1 target types
const TARGET = { club: 'organisation', team: 'team', tournament: 'tournament' }

// Demo personas of the sign-in page -> the backend's demo accounts (POST /auth/demo-login).
const PERSONA = { premium: 'fan', free: 'fan', publisher: 'organiser', scorer: 'organiser', editor: 'editor' }

// ---- matches: the feed and the match page ------------------------------------------------

async function matchList(path) {
  await loadCatalog()
  const page = await v1(path)
  return page.matches.map(A.match)
}

async function liveFeed() {
  await loadCatalog()
  const page = await v1('/matches')
  const matches = page.matches.map(A.match)
  A.ref.matches = matches
  return { now: A.ms(page.server_time) ?? Date.now(), matches, posts: [] }
}

async function tournamentTable(tid) {
  const [page, t] = await Promise.all([v1(`/tournaments/${id(tid)}/standings`), v1(`/tournaments/${id(tid)}`)])
  return A.standings(page, A.format(t.format, t.groups.length))
}

async function scenarioCards(tid, teamId) {
  const [pages, table, schedule] = await Promise.all([
    v1(`/tournaments/${id(tid)}/scenarios${qs({ team_id: teamId })}`),
    tournamentTable(tid),
    v1(`/tournaments/${id(tid)}/schedule`),
  ])
  const matches = schedule.matches.map(A.match)
  return pages.map((p) => A.scenarioCard(p, table, matches))
}

async function matchDetail(matchId) {
  await loadCatalog()
  const page = await v1(`/matches/${id(matchId)}`)
  const m = A.match(page.match)
  const live = page.live_access
  const [events, commentary] = m.status === 'upcoming'
    ? [[], []]
    : await Promise.all([
      v1(`/matches/${id(matchId)}/timeline`).then((t) => t.events).catch(() => []),
      v1(`/matches/${id(matchId)}/commentary`).catch(() => []),
    ])
  const t = A.ref.tournaments[page.tournament_id]
  let stakes = null
  if (m.status === 'upcoming' && t) {
    const cards = await scenarioCards(page.tournament_id).catch(() => [])
    stakes = cards.filter((c) => c.team.id === m.home.id || c.team.id === m.away.id)
  }
  return {
    match: m, access: { liveAllowed: live, reason: live ? null : 'Sign in to follow this match live.' },
    junior: Boolean(t?.is_junior), tournamentName: t?.name ?? m.league, stakes, playersToWatch: null, headToHead: null,
    liveStakes: null, timeline: A.timeline(events, commentary, m), tableImpact: null, playerOfMatch: null,
    updatedAt: Date.now(),
  }
}

// ---- scorer area ---------------------------------------------------------------------------

const PAD_ICON = {
  goal: '⚽', penalty_goal: '🎯', own_goal: '↩', penalty_missed: '✖', yellow_card: '🟨', second_yellow: '🟨',
  red_card: '🟥', substitution: '🔁', shootout_scored: '🎯', shootout_missed: '✖', foul: '✋', timeout: '⏸',
  period_start: '▶', period_end: '⏸', start: '▶',
}
const pads = {} // sport -> EventPad (to turn a button id back into type + payload)
const consoleState = {} // match id -> last v1 ScoringState

function padOf(sportCode, padDef) {
  pads[sportCode] = padDef
  const types = padDef.buttons.map((b) => ({
    id: b.id, label: b.id === 'period_start' ? 'Start next period' : b.label, icon: PAD_ICON[b.id] ?? '•', group: b.group,
    team: b.team, player: b.player, playerPrompt: b.player_prompt, points: b.points, followUp: b.follow_up,
    ball: false, wicket: false, feed: true,
  }))
  types.push({ id: 'start', label: `Start ${padDef.periods[0] ?? 'match'}`, icon: '▶', group: 'control', team: false, player: 'none',
    points: 0, feed: true })
  return { sport: sportCode, pad: 'split', clock: padDef.clock, periodMinutes: null, periods: padDef.periods,
    scoreLabel: padDef.score_label, eventTypes: types }
}

function buttonOf(sportCode, e) {
  const buttons = pads[sportCode]?.buttons ?? []
  const exact = buttons.find((b) => b.type === e.type && Object.entries(b.payload).every(([k, v]) => e.payload?.[k] === v)
    && Object.keys(b.payload).length > 0)
  return (exact ?? buttons.find((b) => b.type === e.type && !Object.keys(b.payload).length))?.id ?? e.type
}

function scorerTeam(t) {
  return A.team(t)
}

function legacyState(s) {
  consoleState[s.match_id] = s
  const home = scorerTeam(s.home)
  const away = scorerTeam(s.away)
  const status = { scheduled: 'upcoming', postponed: 'upcoming', live: 'live' }[s.status] ?? 'finished'
  const started = s.status === 'live' || s.status === 'finished'
  const lastClock = s.events.find((e) => e.clock && !e.undone)?.clock
  const side = (teamId) => (teamId === s.home.id ? 'home' : teamId === s.away.id ? 'away' : null)
  const roster = (rows) => rows.map((p) => ({ id: p.id, number: p.shirt_number ?? 0, name: p.display_name }))
  const label = (teamId, playerId) => {
    const p = [...s.home_roster, ...s.away_roster].find((x) => x.id === playerId)
    return p ? `#${p.shirt_number ?? ''} ${p.display_name}`.trim() : null
  }
  return {
    match: {
      id: s.match_id, code: s.code, sport: s.sport, league: A.ref.tournaments[s.tournament_id]?.name ?? '', status, home, away,
      venue: s.pitch ?? '', score: [s.score.home_goals, s.score.away_goals], clock: lastClock ? parseInt(lastClock, 10) : null,
      period: null, startsAt: A.ms(s.starts_at), tournamentId: s.tournament_id, stage: s.stage,
      dataLevel: s.data_level === 'results' ? 'results_only' : 'live',
    },
    sport: s.sport, started, periodIndex: Math.max(s.period - 1, 0), periodLabel: '', betweenPeriods: s.between_periods,
    clock: { running: s.status === 'live' && !s.between_periods, baseMinute: lastClock ? parseInt(lastClock, 10) : 0,
      baseAt: lastClock ? Date.now() : A.ms(s.server_time) },
    wickets: [0, 0], balls: [0, 0], homeRoster: roster(s.home_roster), awayRoster: roster(s.away_roster),
    events: s.events.map((e) => ({
      seq: e.seq, clientSeq: e.client_seq, deviceId: 'server', type: buttonOf(s.sport, e), team: side(e.team_id),
      playerId: e.player_id, playerLabel: e.player_id ? label(e.team_id, e.player_id) : null,
      minute: e.clock ? parseInt(e.clock, 10) : null, period: (e.period ?? 1) - 1, at: A.ms(e.created_at), undone: e.undone,
    })),
    deviceLastSeq: s.last_client_seq, role: s.role === 'organiser' ? 'admin' : 'scorer', updatedAt: A.ms(s.server_time),
  }
}

async function scoringState(matchId) {
  await loadCatalog()
  const s = await v1(`/matches/${id(matchId)}/scoring`, { scorer: true })
  if (!pads[s.sport]) await v1(`/sports/${id(s.sport)}/event-types`).then((p) => padOf(s.sport, p))
  return legacyState(s)
}

/** One queued tap -> the v1 event it stands for (kick-off, periods, buttons with payloads). */
async function postEvent(matchId, body) {
  const state = consoleState[matchId] ?? (await v1(`/matches/${id(matchId)}/scoring`, { scorer: true }))
  const teamId = body.team === 'home' ? state.home.id : body.team === 'away' ? state.away.id : null
  const send = (event) => v1(`/matches/${id(matchId)}/events`, { method: 'POST', body: event, scorer: true })
  if (body.type === 'start') {
    await v1(`/matches/${id(matchId)}/start`, { method: 'POST', scorer: true })
    await send({ client_seq: body.clientSeq, type: 'period_start', payload: { period: 1 } })
  } else if (body.type === 'period_start' || body.type === 'period_end') {
    const period = body.type === 'period_start' ? state.period + 1 : Math.max(state.period, 1)
    await send({ client_seq: body.clientSeq, type: body.type, payload: { period } })
  } else {
    const button = pads[state.sport]?.buttons.find((b) => b.id === body.type)
    await send({ client_seq: body.clientSeq, type: button?.type ?? body.type, payload: button?.payload ?? {},
      team_id: teamId, player_id: body.playerId ?? null })
  }
  return scoringState(matchId)
}

async function undoEvent(matchId, clientSeq, deviceId, undoSeq) {
  const state = consoleState[matchId] ?? (await v1(`/matches/${id(matchId)}/scoring`, { scorer: true }))
  const target = state.events.find((e) => e.client_seq === clientSeq && !e.undone)
  if (!target) {
    const err = new Error('That event hasn’t reached the server.')
    err.status = 404
    throw err
  }
  const next = undoSeq ?? state.last_client_seq + 1
  await v1(`/matches/${id(matchId)}/events/${target.seq}/undo`, { method: 'POST', body: { client_seq: next }, scorer: true })
  return scoringState(matchId)
}

async function finishScoring(matchId, score) {
  const state = consoleState[matchId]
  const body = { home_goals: score[0], away_goals: score[1] }
  const path = state?.data_level === 'results' || state?.status === 'scheduled' ? 'result' : 'finish'
  return v1(`/matches/${id(matchId)}/${path}`, { method: 'POST', body, scorer: true })
}

async function scoringAssignments() {
  await loadCatalog()
  const rows = await v1('/scoring/me', { scorer: true })
  const today = new Date().toDateString()
  const items = rows.map((r) => {
    const status = { scheduled: 'upcoming', postponed: 'upcoming', live: 'live' }[r.status] ?? 'finished'
    const startsAt = A.ms(r.starts_at)
    const day = status === 'finished' ? 'past' : status === 'live' || new Date(startsAt).toDateString() <= today ? 'today' : 'later'
    return {
      match: { id: r.match_id, code: r.code, sport: r.sport, league: r.tournament_name, status,
        home: A.team(r.home) ?? A.placeholder(null, r.code, 'h'), // knockout teams are known once the groups finish
        away: A.team(r.away) ?? A.placeholder(null, r.code, 'a'), venue: r.pitch ?? '', score: null, startsAt,
        tournamentId: r.tournament_id, stage: r.stage,
        dataLevel: r.data_level === 'results' ? 'results_only' : 'live' },
      clubId: '*', clubName: r.tournament_name, competition: r.tournament_name,
      dataLevel: r.data_level === 'results' ? 'results_only' : 'live', status, day,
      canStart: status === 'live' || (status === 'upcoming' && day === 'today'), eventsRecorded: r.events_recorded,
      lastEventAt: A.ms(r.last_event_at),
    }
  })
  return {
    scorerName: lastMe.signedIn ? lastMe.name : 'Scorer',
    // the scorer header lists who they score for: the tournaments (there are no club roles in v1)
    clubs: [...new Map(rows.map((r) => [r.tournament_id, { id: r.tournament_id, name: r.tournament_name }])).values()],
    active: items.filter((i) => i.status !== 'finished'), past: items.filter((i) => i.status === 'finished').reverse(),
    updatedAt: Date.now(),
  }
}

// ---- search ------------------------------------------------------------------------------

const SEARCH_TYPE = { clubs: 'organisation', teams: 'team', events: 'tournament', players: 'player' }

async function search(params, signal) {
  const { clubs, teams } = await loadCatalog()
  if (!params.q || params.q.trim().length < 2) {
    // no text yet: the filters alone pick from the catalogue
    const keep = (t) => (!params.sport || params.sport === 'all' || t.sport === params.sport)
      && (!params.age || params.age === 'all' || t.ageGroup === params.age)
      && (!params.region || params.region === 'all' || t.region === params.region)
    const list = teams.filter(keep)
    const clubList = clubs.filter((c) => (!params.region || params.region === 'all' || c.region === params.region)
      && (!params.sport || params.sport === 'all' || c.sports.includes(params.sport)))
    const limit = params.limit ?? 50
    const pick = (key, rows) => (!params.type || params.type === 'all' || params.type === key ? rows : [])
    const res = { clubs: pick('clubs', clubList), teams: pick('teams', list), events: [], players: [] }
    return { query: '', total: res.clubs.length + res.teams.length,
      counts: { clubs: res.clubs.length, teams: res.teams.length, events: 0, players: 0 },
      clubs: res.clubs.slice(0, limit), teams: res.teams.slice(0, limit), events: [], players: [] }
  }
  const type = SEARCH_TYPE[params.type]
  const found = await v1(`/search${qs({ q: params.q.trim(), type, sport: params.sport, region: params.region, limit: Math.min(params.limit ?? 10, 50) })}`, { signal })
  const hits = (kind) => found.hits.filter((h) => h.type === kind)
  const clubHits = hits('organisation').map((h) => A.ref.clubs[h.id]).filter(Boolean)
  const teamHits = hits('team').map((h) => A.ref.teams[h.id]).filter(Boolean)
    .filter((t) => !params.age || params.age === 'all' || t.ageGroup === params.age)
  const eventIds = new Set(hits('tournament').map((h) => h.id))
  const events = A.ref.matches.filter((m) => eventIds.has(m.tournamentId) && m.status !== 'finished')
  const players = hits('player').map((h) => {
    const t = teams.find((x) => x.name === h.detail)
    return { id: h.id, name: h.name, number: '', position: '', team: t ?? { id: '', name: h.detail ?? '', short: '?', color: '#6b7280', sport: '' } }
  })
  return {
    query: found.query, total: clubHits.length + teamHits.length + events.length + players.length,
    counts: { clubs: clubHits.length, teams: teamHits.length, events: events.length, players: players.length },
    clubs: clubHits, teams: teamHits, events, players,
  }
}

export const api = {
  // ---- catalogue -------------------------------------------------------------------------
  sports: async () => [{ id: 'all', label: 'All', icon: '' }, ...(await loadCatalog()).sports.map(A.sport)],
  teams: async () => (await loadCatalog()).teams,
  clubs: async () => {
    const { clubs } = await loadCatalog()
    // Keep slug aliases for public organisation links that use slugs in their URLs.
    return [...clubs, ...clubs.filter((c) => c.slug && c.slug !== c.id).map((c) => ({ ...c, id: c.slug }))]
  },
  tournaments: async () => (await loadCatalog()).tournaments.map(A.tournamentSummary),
  searchFilters: async () => {
    const { clubs, teams } = await loadCatalog()
    const towns = [...new Set(clubs.map((c) => c.city).filter(Boolean))].sort()
    const ages = [...new Set(teams.map((t) => t.ageGroup))].sort()
    return { types: SEARCH_TYPES, sports: [], regions: towns.map((t) => ({ id: t, label: t })),
      ageGroups: ages.map((a) => ({ id: a, label: A.ageLabel(a) })) }
  },

  // ---- the fan feed (polled; see useLiveFeed) and search --------------------------------
  liveFeed,
  search,
  nearby: async () => ({ clubs: [], events: [] }), // not in the API: the "Near you" box hides itself
  feed: liveFeed,
  // Not in the API (no posts or comments; clubs join by creating an organisation).
  addComment: () => Promise.reject(Object.assign(new Error('Comments aren’t available.'), { status: 501 })),
  suggestClub: () => Promise.reject(Object.assign(new Error('Ask the club to create its organisation in OurSport.'), { status: 501 })),

  // ---- clubs (organisations) ------------------------------------------------------------
  club: async (clubId) => {
    await loadCatalog()
    const page = await v1(`/organisations/${id(organisationId(clubId))}`)
    A.ref.orgs[page.id] = page
    const known = A.ref.clubs[page.id]
    return A.club(page, known?.teamIds ?? [])
  },
  clubMatches: async (clubId, when) => {
    await loadCatalog()
    const all = await matchList(`/organisations/${id(organisationId(clubId))}/matches`)
    const past = when === 'past'
    const rows = all.filter((m) => (past ? m.status === 'finished' : m.status !== 'finished'))
    if (past) rows.sort((a, b) => b.startsAt - a.startsAt)
    return { when: past ? 'past' : 'upcoming', matches: rows, events: [], total: rows.length, limited: false }
  },
  clubTeams: async (clubId) => {
    await loadCatalog()
    return (await v1(`/organisations/${id(organisationId(clubId))}/teams`)).map((t) => A.ref.teams[t.id] ?? A.team(t))
  },
  clubStories: async (clubId) => {
    await loadCatalog()
    return A.storiesIn(
      (await v1(`/organisations/${id(organisationId(clubId))}/stories?limit=50`)).items,
      lastMe.language,
    )
  },

  // ---- stories --------------------------------------------------------------------------
  story: async (storyId, lang) => {
    await loadCatalog()
    const s = await v1(`/stories/${id(storyId)}`)
    const siblings = s.tournament_id
      ? (await v1(`/tournaments/${id(s.tournament_id)}/stories`).catch(() => []))
        .filter((x) => x.subject_id === s.subject_id && x.kind === s.kind)
      : [s]
    const wanted = lang && lang !== s.language ? siblings.find((x) => x.language === lang) : null
    const chosen = wanted ? await v1(`/stories/${id(wanted.id)}`) : s
    const view = A.story(chosen, siblings.length ? siblings.map((x) => x.language) : [s.language])
    view.facts = chosen.facts.map((f) => {
      const [key, ...rest] = f.claim.split(': ')
      return rest.length ? { key, value: rest.join(': ') } : { key: 'fact', value: f.claim }
    })
    const m = chosen.subject_type === 'match' ? A.ref.matches.find((x) => x.id === chosen.subject_id) : null
    const t = A.ref.tournaments[chosen.tournament_id]
    return {
      story: view,
      related: {
        matches: m ? [m] : [], teams: m ? [m.home, m.away] : [],
        club: chosen.subject_type === 'organisation' ? A.ref.clubs[chosen.subject_id] ?? null : null,
        tournament: t ? { id: t.id, name: t.name } : null,
      },
      sponsors: [],
    }
  },
  reportStoryError: (storyId, message) =>
    v1(`/stories/${id(storyId)}/corrections`, { method: 'POST', body: { kind: 'mistake', text: message } }),
  match: matchDetail,
  matchStories: async (matchId) => A.storiesIn(await v1(`/matches/${id(matchId)}/stories`), lastMe.language),

  // ---- live (GET /live/token, then the match WebSocket) ----------------------------------
  liveToken: (matchId) => v1(`/live/token${qs({ match_id: matchId })}`),
  liveUrl: (matchId, token, sinceSeq = 0) => {
    const base = API_BASE || window.location.origin
    return `${base.replace(/^http/, 'ws')}/api/v1/live/matches/${id(matchId)}?token=${id(token)}&since_seq=${sinceSeq}`
  },

  // ---- events (tournaments) --------------------------------------------------------------
  tournament: async (tid) => {
    await loadCatalog()
    const t = await v1(`/tournaments/${id(tid)}`)
    const teams = t.groups.flatMap((g) => g.teams.map(A.team))
    return {
      id: t.id, name: t.name, sport: t.sport, startsAt: A.ms(t.starts_on), endsAt: A.ms(t.ends_on),
      organiser: { name: t.organisation_name, clubId: t.organisation_id }, venue: '', region: '',
      ...A.format(t.format, t.groups.length),
      resultsOnly: false, junior: t.is_junior, tiebreak: { key: 'gd', label: 'GD', description: 'Goal difference' },
      forLabel: 'GF', againstLabel: 'GA', groups: t.groups.map((g) => ({ id: g.id, name: g.name, teamIds: g.teams.map((x) => x.id) })),
      teams, updatedAt: Date.now(), liveNow: t.live_now, timeZone: t.time_zone, status: t.status,
    }
  },
  standings: tournamentTable,
  scenarios: async (tid) => {
    const [t, cards] = await Promise.all([v1(`/tournaments/${id(tid)}`), scenarioCards(tid)])
    return { tournamentId: tid, updatedAt: Date.now(), qualifyCount: A.format(t.format, t.groups.length).qualifyCount, cards }
  },
  tournamentStories: async (tid) => A.storiesIn(await v1(`/tournaments/${id(tid)}/stories`), lastMe.language),
  rules: async (tid) => {
    const r = await v1(`/tournaments/${id(tid)}/rules/summary${qs({ lang: lastMe.signedIn ? lastMe.language : undefined })}`)
    const t = A.ref.tournaments[tid]
    return {
      tournamentId: r.tournament_id, title: `${t?.name ?? 'Tournament'} — rules in brief`,
      sections: r.lines.map((line) => {
        const [heading, ...text] = line.split(': ')
        return text.length ? { heading, text: text.join(': ') } : { heading: '', text: line }
      }),
    }
  },

  // ---- notifications and the news column -------------------------------------------------
  notifications: async (cursor, limit = 20) => {
    const page = await v1(`/me/notifications${qs({ cursor, limit })}`)
    return { items: page.items.map(A.notification), unreadCount: page.unread_count, nextCursor: page.next_cursor }
  },
  markRead: (body) => v1('/me/notifications/read', { method: 'POST', body: body.all ? {} : { ids: body.ids ?? [] } }),
  news: async (scope, cursor, limit = 10) => {
    const path = scope === 'following' && lastMe.signedIn ? '/me/stories' : '/stories'
    const page = await v1(`${path}${qs({ cursor, limit, lang: lastMe.signedIn ? lastMe.language : undefined })}`)
    return { items: A.storiesIn(page.items, lastMe.language), nextCursor: page.next_cursor }
  },

  // ---- players and teams -----------------------------------------------------------------
  player: async (playerId) => {
    await loadCatalog()
    const p = await v1(`/players/${id(playerId)}`)
    const t = A.team(p.team)
    const recent = A.ref.matches.filter((m) => m.status === 'finished' && (m.home.id === t.id || m.away.id === t.id)).slice(-5)
    return {
      player: { id: p.id, name: p.display_name, number: p.shirt_number ?? '', position: '', team: t },
      visibility: 'public', season: String(new Date().getFullYear()),
      stats: [{ key: 'goals', label: 'Goals', value: String(p.goals) }],
      form: [], milestones: [], recentMatches: recent.reverse().map((m) => ({ match: m, line: '' })),
    }
  },
  teamPage: async (teamId) => {
    await loadCatalog()
    const page = await v1(`/teams/${id(teamId)}`)
    const t = A.ref.teams[page.id] ?? A.team({ ...page, tournament_ids: page.tournaments.map((x) => x.id) })
    const current = page.tournaments.find((x) => x.status === 'active') ?? page.tournaments.find((x) => x.status === 'upcoming')
      ?? page.tournaments[0]
    let scenario = null
    let standings = null
    if (current) {
      const [cards, table] = await Promise.all([
        scenarioCards(current.id, page.id).catch(() => []), tournamentTable(current.id).catch(() => null),
      ])
      scenario = cards[0] ?? null
      const group = table?.groups.find((g) => g.rows.some((r) => r.team.id === page.id))
      if (group) standings = { ...table, group }
    }
    const junior = page.age_group !== 'adult'
    return {
      team: t, clubName: A.ref.orgs[page.organisation_id]?.name ?? null, ageGroupLabel: A.ageLabel(page.age_group), junior,
      competition: current ? { id: current.id, name: current.name, groupName: standings?.group.name ?? '' } : null,
      scenario, standings,
      playersToWatch: page.players.slice(0, 3).map((p) => ({
        player: { id: p.id, name: p.display_name, number: p.shirt_number ?? '', position: '', team: t },
        visibility: 'public', stats: [], form: [], milestone: null,
      })),
      updatedAt: Date.now(),
    }
  },

  // ---- me, follows and sign-in -----------------------------------------------------------
  me,
  follow: async (kind, targetId) => {
    await v1('/me/follows', { method: 'POST', body: { target_type: TARGET[kind], target_id: targetId } })
    return me()
  },
  unfollow: async (kind, targetId) => {
    const followId = lastMe.followIds?.[`${TARGET[kind]}:${targetId}`]
    if (followId) await v1(`/me/follows/${id(followId)}`, { method: 'DELETE' })
    return me()
  },
  myFollows: async () => {
    await loadCatalog()
    const items = (await v1('/me/follows')).map(A.followItem)
    return { clubs: items.filter((i) => i.kind === 'club'), teams: items.filter((i) => i.kind === 'team'),
      events: items.filter((i) => i.kind === 'tournament') }
  },
  setNotifications: async (followId, patch) => {
    const body = Object.fromEntries(Object.entries(patch).map(([k, v]) => [A.NOTIFY_FIELD[k] ?? k, v]))
    return A.followItem(await v1(`/me/follows/${id(followId)}/notifications`, { method: 'PATCH', body }))
  },
  /** Development only (the backend answers 404 elsewhere). */
  demoLogin: async (plan = 'premium') => {
    await v1('/auth/demo-login', { method: 'POST', body: { persona: PERSONA[plan] ?? 'fan' } })
    return me()
  },
  /** Sign-up and sign-in send a magic link; opening it calls `verify`. Both always answer 202. */
  signup: ({ email, name, language, follow }) =>
    v1('/auth/signup', {
      method: 'POST',
      body: {
        email, display_name: name || email.split('@')[0], language, time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        age_13_plus: true, privacy_accepted: true,
        ...(follow ? { follow: { target_type: TARGET[follow.kind], target_id: follow.id } } : {}),
      },
    }),
  requestLink: (email) => v1('/auth/magic-link', { method: 'POST', body: { email } }),
  verify: async (token) => {
    await v1('/auth/magic-link/verify', { method: 'POST', body: { token } })
    return me()
  },
  logout: async () => {
    await v1('/auth/logout', { method: 'POST' }).catch(() => {})
    return me()
  },
  updateMe: async (patch) => {
    const body = {}
    if (patch.name) body.display_name = patch.name
    if (patch.language) body.language = patch.language
    if (patch.timeZone) body.time_zone = patch.timeZone
    await v1('/me', { method: 'PATCH', body })
    return me()
  },
  deleteAccount: async () => {
    await v1('/me', { method: 'DELETE' })
    return me()
  },

  // ---- scorer area (a scorer pass from the pitch QR code, or an organiser's account) ------
  setScorerPass,
  scorerPass,
  scoringAssignments,
  scoringState,
  eventTypes: async (sportCode) => padOf(sportCode, await v1(`/sports/${id(sportCode)}/event-types`)),
  postEvent,
  undoEvent,
  finishScoring,

  // ---- automatic tournament setup (publisher wizard; backend/docs/12-tournament-setup.md) -----
  // Raw v1 shapes (the wizard is built on them). Edits send the draft version as If-Match.
  myOrganisations: async () => {
    const m = await v1('/me')
    return m.memberships.map((x) => ({ id: x.organisation_id, name: x.organisation_name }))
  },
  createOrganisation: (body) => v1('/organisations', { method: 'POST', body: { ...body, accept_processing_terms: true } }),
  acceptProcessingTerms: (orgId) => v1(`/organisations/${id(orgId)}/processing-agreement`, { method: 'POST' }),
  listSetups: () => v1('/setup'),
  startSetup: (body) => v1('/setup', { method: 'POST', body }),
  deleteSetup: (setupId) => v1(`/setup/${id(setupId)}`, { method: 'DELETE' }),
  getSetup: (setupId) => v1(`/setup/${id(setupId)}`),
  /** A file, or pasted text, for one kind: rulebook, team_list, history, venue. */
  addSetupFile: (setupId, kind, { file, text }) => {
    const form = new FormData()
    form.set('kind', kind)
    if (file) form.set('file', file)
    else form.set('text', text)
    return v1(`/setup/${id(setupId)}/files`, { method: 'POST', body: form })
  },
  extractSetup: (setupId) => v1(`/setup/${id(setupId)}/extract`, { method: 'POST' }),
  answerSetup: (setupId, version, answers) =>
    v1(`/setup/${id(setupId)}/answers`, { method: 'POST', body: { answers }, headers: { 'If-Match': `"${version}"` } }),
  changeSetupDraft: (setupId, version, field, value) =>
    v1(`/setup/${id(setupId)}/draft`, { method: 'PATCH', body: { field, value }, headers: { 'If-Match': `"${version}"` } }),
  redrawSetup: (setupId) => v1(`/setup/${id(setupId)}/draw`, { method: 'POST' }),
  regenerateSchedule: (setupId, relaxation = null) =>
    v1(`/setup/${id(setupId)}/schedule`, { method: 'POST', body: { relaxation } }),
  moveSetupMatch: (setupId, code, body) => v1(`/setup/${id(setupId)}/schedule/matches/${id(code)}`, { method: 'PATCH', body }),
  publishSetup: (setupId, version, filmingPolicy) =>
    v1(`/setup/${id(setupId)}/publish`, {
      method: 'POST', body: { filming_policy: filmingPolicy }, headers: { 'If-Match': `"${version}"` },
    }),
  scorerPasses: (tournamentId) => v1(`/tournaments/${id(tournamentId)}/scorer-passes`),

  // ---- not in the v1 contract yet: the older mock-only routes -------------------------------
  // Accept invite and redeem code (T-070)
  invite: (token) => legacy(`/api/invites/${id(token)}`),
  acceptInvite: (token) => legacy(`/api/invites/${id(token)}/accept`, { method: 'POST' }),
  redeemCode: async (code) => {
    await legacy('/api/me/redeem-code', { method: 'POST', body: { code } })
    return me()
  },
  /** Image upload used by the publisher (PNG, JPEG, WebP or GIF, max 2 MB). */
  uploadImage: (file) => legacy('/uploads', { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } }),
  // Publisher portal
  publisherEvents: () => legacy('/publisher/events'),
  createEvent: (basics) => legacy('/tournaments', { method: 'POST', body: basics }),
  eventSetup: (eid) => legacy(`/tournaments/${id(eid)}`),
  patchEvent: (eid, patch) => legacy(`/tournaments/${id(eid)}`, { method: 'PATCH', body: patch }),
  addEventTeam: (eid, body) => legacy(`/tournaments/${id(eid)}/teams`, { method: 'POST', body }),
  removeEventTeam: (eid, teamId) => legacy(`/tournaments/${id(eid)}/teams/${id(teamId)}`, { method: 'DELETE' }),
  importFixtures: (eid, body) => legacy(`/tournaments/${id(eid)}/import`, { method: 'POST', body }),
  uploadRulebook: (eid, file) => legacy(`/tournaments/${id(eid)}/rulebook`, {
    method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-Filename': id(file.name) },
  }),
  rulebookFrom: (eid, body) => legacy(`/tournaments/${id(eid)}/rulebook`, { method: 'POST', body }),
  rulesSummary: (eid) => legacy(`/tournaments/${id(eid)}/rules/summary`),
  patchRulesDraft: (eid, patch) => legacy(`/tournaments/${id(eid)}/rules/draft`, { method: 'PATCH', body: patch }),
  confirmRules: (eid) => legacy(`/tournaments/${id(eid)}/rules/confirm`, { method: 'POST' }),
  retryRules: (eid) => legacy(`/tournaments/${id(eid)}/rules/retry`, { method: 'POST' }),
  rulesStatus: (eid) => legacy(`/tournaments/${id(eid)}/rules/status`),
  addEventMatch: (eid, body) => legacy(`/tournaments/${id(eid)}/matches`, { method: 'POST', body }),
  patchMatch: (matchId, patch) => legacy(`/matches/${id(matchId)}`, { method: 'PATCH', body: patch }),
  deleteMatch: (matchId) => legacy(`/matches/${id(matchId)}`, { method: 'DELETE' }),
  inviteEventScorers: (eid, body) => legacy(`/tournaments/${id(eid)}/scorer-invites`, { method: 'POST', body }),
  removeEventScorer: (eid, scorerId) => legacy(`/tournaments/${id(eid)}/scorers/${id(scorerId)}`, { method: 'DELETE' }),
  eventStories: (eid, params = {}) => legacy(`/tournaments/${id(eid)}/stories${qs(params)}`),
  createPost: (body) => legacy('/stories', { method: 'POST', body }),
  updatePost: (storyId, patch) => legacy(`/stories/${id(storyId)}`, { method: 'PATCH', body: patch }),
  reviewQueue: (scope = 'mine') => legacy(`/review-queue?scope=${scope}`),
  // Editor desk (E1–E3): the v1 editorial API, see ./editor.js
  ...editorDesk({ loadCatalog, me: () => lastMe }),
}
