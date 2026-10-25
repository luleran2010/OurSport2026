import { useState } from 'react'
import TeamBadge from './TeamBadge'
import { useCatalog } from '../app/providers/catalog'
import { clockTime, startsIn } from '../utils/time'

export default function MatchRow({ match, now, followed, onTeam, onOpen }) {
  const [reminded, setReminded] = useState(false)
  const { sportIcon } = useCatalog()
  const { status, home, away, score } = match
  const isFav = followed.includes(home.id) || followed.includes(away.id)

  return (
    <li className={`match-row match-row--${status}${isFav ? ' is-fav' : ''}`}>
      <div className="mr-status">
        {status === 'live' && (
          <>
            <span className="live-pill"><span className="pulse" />LIVE</span>
            {match.clock != null && <span className="mr-sub">{match.clock}′</span>}
          </>
        )}
        {status === 'upcoming' && (
          <>
            <span className="mr-time">{clockTime(match.startsAt)}</span>
            <span className="mr-sub mr-soon">{startsIn(match.startsAt, now)}</span>
          </>
        )}
        {status === 'finished' && <span className="mr-ft">FT</span>}
      </div>

      <div className="mr-teams">
        {[home, away].map((t, i) => (
          <div className="mr-team" key={i}>
            <TeamBadge team={t} size={24} />
            <button className="mr-team-name" onClick={() => onTeam(t.id)}>
              {t.name}
              {followed.includes(t.id) && <span className="fav-star" aria-label="Followed">★</span>}
            </button>
            {status !== 'upcoming' && (
              <span
                className={`mr-score${match.flash === i ? ' is-flash' : ''}${
                  status === 'finished' && score[i] > score[1 - i] ? ' is-winner' : ''
                }`}
              >
                {score[i]}
              </span>
            )}
          </div>
        ))}
      </div>

      {onOpen ? (
        <button className="mr-meta mr-meta--link" onClick={() => onOpen(match.id)} aria-label={`Match details: ${home.name} vs ${away.name}`}>
          <span>{sportIcon(match.sport)} {match.league}</span>
          <span>{match.venue} ›</span>
        </button>
      ) : (
        <div className="mr-meta">
          <span>{sportIcon(match.sport)} {match.league}</span>
          <span>{match.venue}</span>
        </div>
      )}

      <div className="mr-action">
        {status === 'live' && <button className="btn btn--accent btn--sm" onClick={() => onOpen?.(match.id)}>Watch</button>}
        {status === 'upcoming' && (
          <button
            className={`btn btn--ghost btn--sm${reminded ? ' is-on' : ''}`}
            aria-pressed={reminded}
            onClick={() => setReminded((v) => !v)}
          >
            {reminded ? '✓ Reminder' : 'Remind me'}
          </button>
        )}
        {status === 'finished' && <button className="btn btn--ghost btn--sm" onClick={() => onOpen?.(match.id)}>Recap</button>}
      </div>
    </li>
  )
}
