const BADGE = { family_only: 'Family only', members: 'Members only' }
const RESULT_WORD = { W: 'Win', D: 'Draw', L: 'Loss' }

/** A player to watch (team page F4): a few season stats, recent form and the next milestone. */
export default function PlayerSpotlight({ spot, onNavigate }) {
  const { player, visibility, stats, form, milestone } = spot
  return (
    <article className="spotlight">
      <header className="spotlight-head">
        <span className="spotlight-num" aria-hidden="true">{player.number}</span>
        <div className="spotlight-name">
          <button className="st-team" onClick={() => onNavigate({ type: 'player', playerId: player.id })}>
            <strong>{player.name}</strong>
          </button>
          <span className="page-sub">#{player.number} · {player.position}</span>
        </div>
        {BADGE[visibility] && <span className={`spotlight-badge spotlight-badge--${visibility}`}>{BADGE[visibility]}</span>}
      </header>
      {stats.length > 0 && (
        <dl className="spotlight-stats">
          {stats.map((s) => (
            <div key={s.key}>
              <dt>{s.label}</dt>
              <dd>{s.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {form.length > 0 && (
        <div className="spotlight-form">
          <span className="page-sub">Form</span>
          <ol className="form" aria-label="Last games, oldest first">
            {form.map((f) => (
              <li key={f.matchId} className={`form-pip form-pip--${f.result}`} title={`${RESULT_WORD[f.result]}: ${f.contribution}`}>
                {f.result}
                <span className="sr-only"> ({RESULT_WORD[f.result]}, {f.contribution})</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {milestone && (
        <p className="spotlight-milestone">
          <span aria-hidden="true">{milestone.achieved ? '★' : '◎'}</span> {milestone.title}
          {!milestone.achieved && milestone.target != null && (
            <span className="page-sub"> · {milestone.progress} / {milestone.target}</span>
          )}
        </p>
      )}
    </article>
  )
}
