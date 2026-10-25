import { useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import TeamBadge from '../../components/TeamBadge'
import MatchRow from '../../components/MatchRow'
import Loading from '../../components/Loading'
import ScenarioCard from '../../components/ScenarioCard'
import StandingsTable from '../../components/StandingsTable'
import { FollowButton } from './components/explore/ResultRows'
import { useCatalog } from '../../app/providers/catalog'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { clockTime, dayLabel, formatDateRange, formatDateTime, timeAgo } from '../../utils/time'

const TABS = [
  { id: 'standings', label: 'Standings' },
  { id: 'fixtures', label: 'Fixtures' },
  { id: 'scenarios', label: 'Scenarios' },
  { id: 'news', label: 'News' },
  { id: 'rules', label: 'Rules' },
]

// ---- Standings -----------------------------------------------------------

function StandingsTab({ event, version, onNavigate }) {
  const state = useLoad(() => api.standings(event.id), `${event.id}:${version}`)
  return (
    <Loading state={state} empty="No standings yet.">
      {(data) => (
        <>
          {data.groups.map((g) => <StandingsTable key={g.id} group={g} data={data} onNavigate={onNavigate} />)}
          <p className="st-legend">
            {data.qualifyCount > 0
              ? `Top ${data.qualifyCount} in each ${data.groups.length > 1 ? 'group' : 'table'}${data.bestOfRest ? ` and the best ${data.bestOfRest} of the rest` : ''} go through`
              : 'The table decides the final places'} ·{' '}
            <span className="st-status st-status--through">✓</span> through ·{' '}
            <span className="st-status st-status--out">✕</span> out · {data.tiebreak.label} = {data.tiebreak.description}.
            Live games count once they finish.
            {event.junior && ' Junior event: individual player statistics are not shown, to protect young players.'}
          </p>
          {data.topScorers && (
            <section className="section" aria-labelledby="scorers-h">
              <div className="section-head"><h2 id="scorers-h">Top scorers</h2></div>
              <ol className="scorers">
                {data.topScorers.map((s, i) => (
                  <li key={s.playerName}>
                    <span className="scorer-pos">{i + 1}</span>
                    <TeamBadge team={s.team} size={24} />
                    <span className="scorer-name">{s.playerName}<span>{s.team.name}</span></span>
                    <strong>{s.goals}</strong>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </Loading>
  )
}

// ---- Fixtures (live from the feed stream) --------------------------------

function FixturesTab({ fixtures, now, followed, onNavigate }) {
  if (!fixtures.length) return <p className="empty">No fixtures yet.</p>
  const at = (m) => m.startsAt ?? m.endedAt
  const sorted = [...fixtures].sort((a, b) => at(a) - at(b))
  const groups = []
  for (const m of sorted) {
    const label = dayLabel(at(m), now)
    let g = groups.find((x) => x.label === label)
    if (!g) groups.push((g = { label, items: [] }))
    g.items.push(m)
  }
  return (
    <div className="match-groups">
      {groups.map((g) => (
        <div className="match-group" key={g.label}>
          <h3 className="group-label">
            {g.label}
            {g.items.some((m) => m.status === 'live') && <span className="day-live"> · games live now</span>}
          </h3>
          <ul className="match-list">
            {g.items.map((m) => (
              <MatchRow
                key={m.id}
                match={{ ...m, league: m.stage ?? m.league }}
                now={now}
                followed={followed}
                onTeam={(teamId) => onNavigate({ type: 'team', teamId })}
                onOpen={(matchId) => onNavigate({ type: 'match', matchId })}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

// ---- Scenarios -------------------------------------------------------------

function ScenariosTab({ event, version, now, followed, onNavigate }) {
  const [mine, setMine] = useState(false)
  const state = useLoad(() => api.scenarios(event.id), `${event.id}:${version}`)
  return (
    <>
      <div className="tabs scenario-filter" role="group" aria-label="Show scenarios for">
        <button className={!mine ? 'is-active' : ''} aria-pressed={!mine} onClick={() => setMine(false)}>All teams</button>
        <button className={mine ? 'is-active' : ''} aria-pressed={mine} onClick={() => setMine(true)}>My teams</button>
      </div>
      <Loading state={state} empty="No scenarios.">
        {(data) => {
          const cards = mine ? data.cards.filter((c) => followed.includes(c.team.id)) : data.cards
          if (!cards.length) {
            return mine ? (
              <p className="empty">None of the teams you follow are in this event. Follow a team (or its club) to see it here.</p>
            ) : null
          }
          return (
            <>
              <div className="scenario-grid">
                {cards.map((c) => <ScenarioCard key={c.team.id} card={c} now={now} onNavigate={onNavigate} />)}
              </div>
              <p className="st-legend">Worked out from every possible result of the remaining games. Updated {clockTime(data.updatedAt)}.</p>
            </>
          )
        }}
      </Loading>
    </>
  )
}

// ---- News & rules ------------------------------------------------------------

function NewsTab({ event, now, onNavigate }) {
  const state = useLoad(() => api.tournamentStories(event.id), event.id)
  return (
    <Loading state={state} empty="No news yet.">
      {(stories) =>
        stories.length ? (
          <div className="story-list">
            {stories.map((s) => (
              <button key={s.id} className="story-card" onClick={() => onNavigate({ type: 'story', storyId: s.id })}>
                <span className="story-meta"><span className="story-tag">{s.tag}</span>{timeAgo(s.publishedAt, now)}</span>
                <strong className="story-title">{s.title}</strong>
                <span className="story-summary">{s.summary}</span>
              </button>
            ))}
          </div>
        ) : null
      }
    </Loading>
  )
}

function RulesTab({ event }) {
  const state = useLoad(() => api.rules(event.id), event.id)
  return (
    <Loading state={state} empty="No rules published.">
      {(rules) => (
        <div className="rules">
          <p className="page-sub">{rules.title}</p>
          <dl>
            {rules.sections.map((s) => (
              <div key={s.heading} className="rule">
                <dt>{s.heading}</dt>
                <dd>{s.text}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </Loading>
  )
}

// ---- Page ----------------------------------------------------------------------

export default function EventView({ eventId, matches, now, followed, follow, onNavigate }) {
  const { sportIcon, sportLabel, clubs } = useCatalog()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const tab = TABS.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'standings'
  const eventState = useLoad(() => api.tournament(eventId), eventId)

  if (eventState.status === 'error') return <p className="empty">Event not found.</p>
  if (!eventState.data) return <p className="page-sub">Loading event…</p>

  const event = eventState.data
  const fixtures = matches.filter((m) => m.tournamentId === event.id)
  const liveCount = fixtures.filter((m) => m.status === 'live').length
  // Standings/scenarios reload whenever a game in this event finishes.
  const version = fixtures.filter((m) => m.status === 'finished').map((m) => m.id).join(',')
  const lastUpdated = Math.max(event.updatedAt, now)
  const organiserClub = event.organiser.clubId && clubs[event.organiser.clubId]
  const setTab = (id) => setParams(id === 'standings' ? {} : { tab: id }, { replace: true, state: location.state })
  const shared = { event, version, now, followed, onNavigate }

  return (
    <>
      <header className="event-hero">
        <div className="event-hero-text">
          <div className="club-sports">
            <span className="sport-tag">{sportIcon(event.sport)} {sportLabel(event.sport)}</span>
            {event.resultsOnly && <span className="sport-tag">Results only</span>}
            {liveCount > 0 && <span className="live-pill"><span className="pulse" />{liveCount} LIVE</span>}
          </div>
          <h1>{event.name}</h1>
          <p className="page-sub">📅 {formatDateRange(event.startsAt, event.endsAt)} · 📍 {event.venue}</p>
          <p className="page-sub">
            Organised by{' '}
            {organiserClub ? (
              <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'club', clubId: organiserClub.id })}>
                {event.organiser.name}
              </button>
            ) : (
              event.organiser.name
            )}
            {' '}· {event.format}
          </p>
        </div>
        <div className="event-hero-side">
          <FollowButton on={follow.isTournamentFollowed(event.id)} label={event.name} onToggle={() => follow.toggleTournament(event.id)}>
            ＋ Follow
          </FollowButton>
          <span className="last-updated" title={formatDateTime(lastUpdated)}>
            Last updated {clockTime(lastUpdated)}
          </span>
        </div>
      </header>

      <div className="club-tabs" role="tablist" aria-label="Event sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`etab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="event-panel"
            className={tab === t.id ? 'is-active' : ''}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'fixtures' && liveCount > 0 && <span className="tab-live" aria-label={`${liveCount} live`} />}
          </button>
        ))}
      </div>

      <section id="event-panel" role="tabpanel" aria-labelledby={`etab-${tab}`} className="club-panel">
        {tab === 'standings' && <StandingsTab {...shared} />}
        {tab === 'fixtures' && <FixturesTab fixtures={fixtures} now={now} followed={followed} onNavigate={onNavigate} />}
        {tab === 'scenarios' && <ScenariosTab {...shared} />}
        {tab === 'news' && <NewsTab {...shared} />}
        {tab === 'rules' && <RulesTab {...shared} />}
      </section>
    </>
  )
}
