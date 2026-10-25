import MatchList from '../../components/MatchList'
import FollowSomethingPrompt from './components/FollowSomethingPrompt'
import ScopeNote from './components/ScopeNote'

const CONFIG = {
  schedule: {
    title: 'Schedule',
    sub: 'Upcoming games across all sports',
    memberSub: 'Upcoming games',
    empty: 'No upcoming games.',
    memberEmpty: 'No upcoming games for what you follow.',
    filter: (m) => m.status === 'upcoming',
    sort: (a, b) => a.startsAt - b.startsAt,
  },
  results: {
    title: 'Results',
    sub: 'Final scores from recent games',
    memberSub: 'Final scores',
    empty: 'No results yet.',
    memberEmpty: 'No recent results for what you follow.',
    filter: (m) => m.status === 'finished',
    sort: (a, b) => b.endedAt - a.endedAt,
  },
}

export default function MatchesView({ kind, matches, now, followed, member, followsNothing, onNavigate }) {
  const c = CONFIG[kind]
  const list = matches.filter(c.filter).sort(c.sort)
  return (
    <>
      <div className="page-head">
        <h1>{c.title}</h1>
        <p className="page-sub">
          {member ? c.memberSub : c.sub}
          {!followsNothing && <ScopeNote member={member} onNavigate={onNavigate} />}
        </p>
      </div>
      {followsNothing ? (
        <FollowSomethingPrompt onNavigate={onNavigate} />
      ) : (
        <MatchList
          matches={list}
          now={now}
          followed={followed}
          onTeam={(teamId) => onNavigate({ type: 'team', teamId })}
          onOpen={(matchId) => onNavigate({ type: 'match', matchId })}
          empty={member ? c.memberEmpty : c.empty}
        />
      )}
    </>
  )
}
