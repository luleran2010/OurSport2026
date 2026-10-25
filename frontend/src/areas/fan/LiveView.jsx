import LiveMatchCard from './components/LiveMatchCard'
import FollowSomethingPrompt from './components/FollowSomethingPrompt'
import ScopeNote from './components/ScopeNote'

export default function LiveView({ matches, member, followsNothing, onNavigate }) {
  const live = matches.filter((m) => m.status === 'live')
  return (
    <>
      <div className="page-head">
        <h1>Live now</h1>
        <p className="page-sub">
          {live.length} game{live.length === 1 ? '' : 's'} in progress
          {!followsNothing && <ScopeNote member={member} onNavigate={onNavigate} />}
        </p>
      </div>
      {followsNothing ? (
        <FollowSomethingPrompt onNavigate={onNavigate} />
      ) : live.length ? (
        <div className="live-grid">
          {live.map((m) => <LiveMatchCard key={m.id} match={m} onWatch={() => onNavigate({ type: 'match', matchId: m.id })} />)}
        </div>
      ) : (
        <p className="empty">{member ? 'None of what you follow is playing right now.' : 'No games in progress right now.'}</p>
      )}
    </>
  )
}
