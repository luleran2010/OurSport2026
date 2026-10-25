import TeamBadge from '../../../components/TeamBadge'

export default function LiveMatchCard({ match, onWatch }) {
  const { home, away, score, flash } = match
  return (
    <article className="live-card" aria-label={`${home.name} vs ${away.name}, live`}>
      <div className="live-card-top">
        <span className="live-pill"><span className="pulse" />LIVE</span>
        <span className="clock">{[match.clock != null && `${match.clock}′`, match.period].filter(Boolean).join(' · ')}</span>
      </div>
      <div className="live-card-teams">
        {[home, away].map((t, i) => (
          <div className="team-row" key={i}>
            <TeamBadge team={t} />
            <span className="team-name">{t.name}</span>
            <span className={`score${flash === i ? ' is-flash' : ''}`}>{score[i]}</span>
          </div>
        ))}
      </div>
      <div className="live-card-foot">
        <span className="league">{match.league}</span>
        {match.viewers != null && <span className="viewers">👁 {match.viewers}</span>}
      </div>
      <button className="watch-btn" onClick={onWatch}>Watch live</button>
    </article>
  )
}
