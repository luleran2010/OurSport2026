import TeamBadge from '../../components/TeamBadge'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { dayLabel, formatDate } from '../../utils/time'

const VIS_LABEL = { public: 'Public profile', members: 'Visible to members' }
const RESULT_WORD = { W: 'Win', D: 'Draw', L: 'Loss' }

function PrivateProfile({ code, signedIn, onSignIn }) {
  return (
    <div className="premium-lock private-profile">
      <span className="lock-icon" aria-hidden="true">🔒</span>
      <div>
        <h1>This profile is private</h1>
        {code === 'members_only' && !signedIn ? (
          <>
            <p>The player has chosen to show their profile to signed-in members only.</p>
            <div className="lock-actions"><button className="btn btn--accent btn--sm" onClick={onSignIn}>Log in to see it</button></div>
          </>
        ) : (
          <p>The player (or, for junior players, their guardian) has not made this profile public.</p>
        )}
      </div>
    </div>
  )
}

export default function PlayerView({ playerId, now, onNavigate }) {
  const { sportIcon, sportLabel } = useCatalog()
  const { me, requestLogin } = useMeContext()
  const signedIn = Boolean(me?.signedIn)
  const state = useLoad(() => api.player(playerId), `${playerId}:${signedIn}`)

  if (state.status === 'error') {
    if (state.error?.status === 403) return <PrivateProfile code={state.error.code} signedIn={signedIn} onSignIn={() => requestLogin()} />
    return <p className="empty">{state.error?.status === 404 ? 'Player not found.' : 'Couldn’t load this profile right now.'}</p>
  }
  if (!state.data) return <p className="page-sub">Loading player…</p>

  const { player, visibility, season, stats, form, milestones, recentMatches } = state.data
  const { team } = player

  return (
    <>
      <header className="player-hero" style={{ '--team': team.color }}>
        <span className="player-hero-num" aria-hidden="true">{player.number}</span>
        <div className="player-hero-text">
          <span className="sport-tag">{VIS_LABEL[visibility]}</span>
          <h1>{player.name}</h1>
          <p className="page-sub">#{player.number} · {player.position} · {sportIcon(team.sport)} {sportLabel(team.sport)}</p>
          <button className="related-team" onClick={() => onNavigate({ type: 'team', teamId: team.id })}>
            <TeamBadge team={team} size={22} /> {team.name}
          </button>
        </div>
      </header>

      <section className="section" aria-labelledby="season-h">
        <div className="section-head"><h2 id="season-h">Season {season}</h2></div>
        <dl className="stat-grid">
          {stats.map((s) => (
            <div key={s.key} className="stat-tile">
              <dt>{s.label}</dt>
              <dd>{s.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {form.length > 0 && (
        <section className="section" aria-labelledby="form-h">
          <div className="section-head">
            <h2 id="form-h">Form</h2>
            <span className="page-sub">last {form.length}, oldest → newest</span>
          </div>
          <ol className="form-strip">
            {form.map((f) => (
              <li key={f.matchId}>
                <button
                  className={`form-card form-card--${f.result}`}
                  onClick={() => onNavigate({ type: 'match', matchId: f.matchId })}
                  title={`${RESULT_WORD[f.result]} · ${f.contribution}`}
                >
                  <span className="form-result">{f.result}</span>
                  <span className="form-line">{f.contribution}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="section" aria-labelledby="ms-h">
        <div className="section-head"><h2 id="ms-h">Milestones</h2></div>
        <ul className="milestones">
          {milestones.map((m) => (
            <li key={m.title} className={m.achieved ? 'is-done' : ''}>
              <span className="ms-icon" aria-hidden="true">{m.achieved ? '★' : '☆'}</span>
              <div className="ms-text">
                <strong>{m.title}</strong>
                {m.achieved && m.date && (
                  <span className="page-sub">{formatDate(m.date)}</span>
                )}
                {!m.achieved && m.target && (
                  <span className="ms-progress" role="progressbar" aria-valuenow={m.progress} aria-valuemin={0} aria-valuemax={m.target}>
                    <span style={{ width: `${(100 * m.progress) / m.target}%` }} />
                  </span>
                )}
              </div>
              {!m.achieved && m.target && <span className="ms-count">{m.progress}/{m.target}</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="section" aria-labelledby="rm-h">
        <div className="section-head"><h2 id="rm-h">Recent matches</h2></div>
        {recentMatches.length ? (
          <ul className="h2h-list recent-list">
            {recentMatches.map(({ match: m, line }) => {
              const side = m.home.id === team.id ? 0 : 1
              const opp = side === 0 ? m.away : m.home
              const res = m.score[side] > m.score[1 - side] ? 'W' : m.score[side] < m.score[1 - side] ? 'L' : 'D'
              return (
                <li key={m.id}>
                  <button className="recent-row" onClick={() => onNavigate({ type: 'match', matchId: m.id })}>
                    <span className="h2h-date">{dayLabel(m.endedAt, now)}</span>
                    <span className={`form-pip form-pip--${res}`}>{res}</span>
                    <span className="recent-game">
                      {side === 0 ? 'vs' : '@'} <TeamBadge team={opp} size={18} /> {opp.name}{' '}
                      <strong>{m.score[side]}–{m.score[1 - side]}</strong>
                    </span>
                    <span className="recent-line">{line}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="empty">No recent matches in OurSport yet.</p>
        )}
      </section>
    </>
  )
}
