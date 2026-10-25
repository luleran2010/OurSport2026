import { useLocation, useSearchParams } from 'react-router'
import ClubCrest from '../../components/ClubCrest'
import MatchRow from '../../components/MatchRow'
import MatchList from '../../components/MatchList'
import { FollowButton, TeamRow } from './components/explore/ResultRows'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { api } from '../../api/client'
import { useLoad } from '../../api/useLoad'
import Loading from '../../components/Loading'
import { clockTime, dayLabel, timeAgo } from '../../utils/time'

const TABS = [
  { id: 'upcoming', label: 'Upcoming' },
  { id: 'results', label: 'Results' },
  { id: 'teams', label: 'Teams' },
  { id: 'news', label: 'News' },
]

function EventRow({ event }) {
  return (
    <li className="match-row match-row--event">
      <div className="mr-status">
        <span className="mr-time">{clockTime(event.startsAt)}</span>
      </div>
      <div className="event-text">
        <span className="event-tag">Club event</span>
        <strong>{event.title}</strong>
        {event.description && <span className="event-desc">{event.description}</span>}
      </div>
      <div className="mr-meta"><span>📍 {event.venue}</span></div>
      <div className="mr-action" />
    </li>
  )
}

function UpcomingTab({ clubId, liveMatches, now, followed, onNavigate }) {
  const { me, requestLogin } = useMeContext()
  const signedIn = Boolean(me?.signedIn)
  const state = useLoad(() => api.clubMatches(clubId, 'upcoming'), `${clubId}:${signedIn}`)

  return (
    <Loading state={state} empty="Nothing coming up yet.">
      {(data) => {
        // Prefer the live-updating copy of each match from the feed stream.
        const byId = new Map(liveMatches.map((m) => [m.id, m]))
        const items = [
          ...data.matches.map((m) => ({ kind: 'match', at: m.status === 'live' ? 0 : m.startsAt, item: byId.get(m.id) ?? m })),
          ...data.events.map((e) => ({ kind: 'event', at: e.startsAt, item: e })),
        ].sort((a, b) => a.at - b.at)
        if (!items.length) return null

        const groups = []
        for (const it of items) {
          const label = it.kind === 'match' && it.item.status === 'live' ? 'In progress' : dayLabel(it.at, now)
          let g = groups.find((x) => x.label === label)
          if (!g) groups.push((g = { label, items: [] }))
          g.items.push(it)
        }
        return (
          <>
            <div className="match-groups">
              {groups.map((g) => (
                <div className="match-group" key={g.label}>
                  <h3 className="group-label">{g.label}</h3>
                  <ul className="match-list">
                    {g.items.map(({ kind, item }) =>
                      kind === 'match' ? (
                        <MatchRow
                          key={item.id}
                          match={item}
                          now={now}
                          followed={followed}
                          onTeam={(teamId) => onNavigate({ type: 'team', teamId })}
                          onOpen={(matchId) => onNavigate({ type: 'match', matchId })}
                        />
                      ) : (
                        <EventRow key={item.id} event={item} />
                      ),
                    )}
                  </ul>
                </div>
              ))}
            </div>
            {data.limited && (
              <div className="members-gate">
                <div>
                  <strong>Showing the next {items.length} of {data.total}</strong>
                  <span>Log in to see all upcoming matches and club events.</span>
                </div>
                <button className="btn btn--accent btn--sm" onClick={() => requestLogin()}>Log in to see all</button>
              </div>
            )}
          </>
        )
      }}
    </Loading>
  )
}

function ResultsTab({ clubId, now, followed, onNavigate }) {
  const state = useLoad(() => api.clubMatches(clubId, 'past'), clubId)
  return (
    <Loading state={state} empty="No results yet.">
      {(data) =>
        data.matches.length ? (
          <MatchList
            matches={data.matches}
            now={now}
            followed={followed}
            onTeam={(teamId) => onNavigate({ type: 'team', teamId })}
            onOpen={(matchId) => onNavigate({ type: 'match', matchId })}
          />
        ) : null
      }
    </Loading>
  )
}

function TeamsTab({ clubId, follow, onNavigate }) {
  const state = useLoad(() => api.clubTeams(clubId), clubId)
  return (
    <Loading state={state} empty="This club has no teams listed yet.">
      {(teams) =>
        teams.length ? (
          <ul className="result-list">
            {teams.map((t) => <TeamRow key={t.id} team={t} follow={follow} onNavigate={onNavigate} />)}
          </ul>
        ) : null
      }
    </Loading>
  )
}

function NewsTab({ clubId, now, onNavigate }) {
  const state = useLoad(() => api.clubStories(clubId), clubId)
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

export default function ClubView({ clubId, matches, now, followed, follow, onNavigate }) {
  const { sportIcon, sportLabel, regionLabel } = useCatalog()
  const { me } = useMeContext()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const tab = TABS.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'upcoming'
  const clubState = useLoad(() => api.club(clubId), clubId)

  if (clubState.status === 'error') return <p className="empty">Club not found.</p>
  if (!clubState.data) return <p className="page-sub">Loading club…</p>

  const club = clubState.data
  const following = follow.isClubFollowed(club.id)
  const premiumHere = me?.premium?.viaClubId === club.id
  const setTab = (id) => setParams(id === 'upcoming' ? {} : { tab: id }, { replace: true, state: location.state })
  const shared = { clubId: club.id, now, followed, follow, onNavigate }
  const sponsors = club.sponsors.filter((s) => !s.showOn || s.showOn.includes('club_page'))

  return (
    <>
      <header className="club-hero" style={{ '--team': club.color }}>
        <ClubCrest club={club} size={76} />
        <div className="club-hero-text">
          {premiumHere && <span className="premium-badge">★ Premium via this club</span>}
          <h1>{club.name}</h1>
          <div className="club-sports">
            {club.sports.map((s) => (
              <span key={s} className="sport-tag">{sportIcon(s)} {sportLabel(s)}</span>
            ))}
          </div>
          <p className="page-sub">📍 {club.city}, {regionLabel(club.region)} · Home: {club.venue}</p>
          {club.description && <p className="club-desc">{club.description}</p>}
        </div>
        <FollowButton on={following} label={club.name} onToggle={() => follow.toggleClub(club.id)}>
          ＋ Follow
        </FollowButton>
      </header>

      <div className="club-tabs" role="tablist" aria-label="Club sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="club-panel"
            className={tab === t.id ? 'is-active' : ''}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section id="club-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="club-panel">
        {tab === 'upcoming' && <UpcomingTab {...shared} liveMatches={matches} />}
        {tab === 'results' && <ResultsTab {...shared} />}
        {tab === 'teams' && <TeamsTab {...shared} />}
        {tab === 'news' && <NewsTab {...shared} />}
      </section>

      {sponsors.length > 0 && (
        <footer className="sponsor-strip" aria-label={`${club.name} sponsors`}>
          <span className="sponsor-label">Supported by</span>
          <ul>
            {sponsors.map((s) => {
              const mark = s.logoUrl ? <img src={s.logoUrl} alt={s.name} /> : <span className="sponsor-wordmark">{s.name}</span>
              return (
                <li key={s.id || s.name}>
                  {s.url ? <a href={s.url} target="_blank" rel="sponsored noopener noreferrer">{mark}</a> : mark}
                </li>
              )
            })}
          </ul>
        </footer>
      )}
    </>
  )
}
