import { useMemo, useState } from 'react'
import LiveCarousel from './components/LiveCarousel'
import SportFilter from './components/SportFilter'
import MatchList from '../../components/MatchList'
import FollowSomethingPrompt from './components/FollowSomethingPrompt'
import ScopeNote from './components/ScopeNote'
import { formatWeekday } from '../../utils/time'

export default function HomeView({ matches, now, followed, member, followsNothing, onNavigate }) {
  const [sport, setSport] = useState('all')
  const bySport = (m) => sport === 'all' || m.sport === sport

  const todayNext = matches
    .filter((m) => (m.status === 'live' || m.status === 'upcoming') && bySport(m))
    .sort((a, b) => (a.status === 'live' ? -1 : b.status === 'live' ? 1 : a.startsAt - b.startsAt))
  const results = matches
    .filter((m) => m.status === 'finished' && bySport(m))
    .sort((a, b) => b.endedAt - a.endedAt)

  const liveCounts = useMemo(() => {
    const c = { all: 0 }
    for (const m of matches) {
      if (m.status !== 'live') continue
      c.all += 1
      c[m.sport] = (c[m.sport] ?? 0) + 1
    }
    return c
  }, [matches])

  const onTeam = (teamId) => onNavigate({ type: 'team', teamId })
  const onOpen = (matchId) => onNavigate({ type: 'match', matchId })
  const dateStr = formatWeekday(now)

  return (
    <>
      <div className="page-head">
        <h1>Home feed</h1>
        <p className="page-sub">
          {dateStr}
          {!followsNothing && <ScopeNote member={member} onNavigate={onNavigate} />}
        </p>
      </div>

      {followsNothing ? (
        <FollowSomethingPrompt onNavigate={onNavigate} />
      ) : (
      <>

      <section className="section section--first" aria-labelledby="live-h">
        <div className="section-head">
          <h2 id="live-h"><span className="live-dot" aria-hidden="true" /> Live now</h2>
          <button className="link-btn" onClick={() => onNavigate({ type: 'live' })}>See all</button>
        </div>
        <LiveCarousel matches={matches} onWatch={(m) => onNavigate({ type: 'match', matchId: m.id })} />
      </section>

      <SportFilter value={sport} onChange={setSport} liveCounts={liveCounts} />

      <section className="section" aria-labelledby="today-h">
        <div className="section-head">
          <h2 id="today-h">Today &amp; next</h2>
          <button className="link-btn" onClick={() => onNavigate({ type: 'schedule' })}>Full schedule</button>
        </div>
        <MatchList matches={todayNext} now={now} followed={followed} onTeam={onTeam} onOpen={onOpen} empty={member ? 'Nothing scheduled for what you follow.' : 'Nothing scheduled for this sport.'} />
      </section>

      <section className="section" aria-labelledby="results-h">
        <div className="section-head">
          <h2 id="results-h">Latest results</h2>
          <button className="link-btn" onClick={() => onNavigate({ type: 'results' })}>All results</button>
        </div>
        <MatchList matches={results} now={now} followed={followed} onTeam={onTeam} onOpen={onOpen} empty={member ? 'No recent results for what you follow.' : 'No recent results.'} />
      </section>
      </>
      )}
    </>
  )
}
