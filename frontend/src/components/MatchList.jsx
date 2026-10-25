import MatchRow from './MatchRow'
import { dayLabel } from '../utils/time'

function groupMatches(matches, now) {
  const groups = []
  for (const m of matches) {
    const label =
      m.status === 'live' ? 'In progress' : dayLabel(m.status === 'upcoming' ? m.startsAt : m.endedAt, now)
    let g = groups.find((x) => x.label === label)
    if (!g) groups.push((g = { label, items: [] }))
    g.items.push(m)
  }
  return groups
}

export default function MatchList({ matches, now, followed, onTeam, onOpen, empty = 'No games.' }) {
  if (!matches.length) return <p className="empty">{empty}</p>
  return (
    <div className="match-groups">
      {groupMatches(matches, now).map((g) => (
        <div className="match-group" key={g.label}>
          <h3 className="group-label">{g.label}</h3>
          <ul className="match-list">
            {g.items.map((m) => (
              <MatchRow key={m.id} match={m} now={now} followed={followed} onTeam={onTeam} onOpen={onOpen} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
