import TeamBadge from './TeamBadge'
import { clockTime, dayLabel } from '../utils/time'

const STATUS_LABEL = { through: 'Through', out: 'Out', alive: 'Still in it' }

/** What a team needs in a tournament (from /tournaments/{id}/scenarios). */
export default function ScenarioCard({ card, now, onNavigate }) {
  return (
    <article className={`scenario scenario--${card.status}`}>
      <header className="scenario-head">
        <TeamBadge team={card.team} size={36} />
        <div className="scenario-team">
          <button className="st-team" onClick={() => onNavigate({ type: 'team', teamId: card.team.id })}>
            <strong>{card.team.name}</strong>
          </button>
          <span className="page-sub">{card.groupName} · {card.position}. place · {card.points} pts</span>
        </div>
        <span className={`scenario-pill scenario-pill--${card.status}`}>{STATUS_LABEL[card.status]}</span>
      </header>
      <p className="scenario-headline">{card.headline}</p>
      <p className="scenario-detail">{card.detail}</p>
      {card.remaining.length > 0 && (
        <ul className="scenario-games">
          {card.remaining.map((f) => (
            <li key={f.matchId}>
              <button onClick={() => onNavigate({ type: 'match', matchId: f.matchId })}>
                vs <TeamBadge team={f.opponent} size={18} /> {f.opponent.name}
                <span className={f.status === 'live' ? 'sg-live' : 'sg-when'}>
                  {f.status === 'live' ? 'LIVE' : `${dayLabel(f.startsAt, now)} ${clockTime(f.startsAt)}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}
