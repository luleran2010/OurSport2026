import TeamBadge from '../../components/TeamBadge'
import ScenarioCard from '../../components/ScenarioCard'
import StoryCard from '../../components/StoryCard'
import ShareButton from '../../components/ShareButton'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { useLiveMatch } from '../../live/useLiveMatch'
import { api } from '../../api/client'
import { clockTime, dayLabel } from '../../utils/time'

const KIND_ICON = { kickoff: '▶', goal: '⚽', insight: '✦', fulltime: '■', info: 'ℹ', period: '⏸', correction: '↩', event: '•' }

function CorrectionBanner({ correction }) {
  return (
    <div className="notice notice--correction" role="status">
      <strong>Correction</strong>
      <span>{correction.message}</span>
      <span className="notice-time">Updated {clockTime(correction.at)}</span>
    </div>
  )
}

function MatchHeader({ match, competition, now, premium, liveStatus, onNavigate }) {
  const { home, away, status } = match
  const showScore = status === 'finished' || (status === 'live' && premium && match.score)
  return (
    <div className="match-hero" style={{ '--home': home.color, '--away': away.color }}>
      <div className="match-hero-top">
        {status === 'live' ? (
          <span className="live-pill"><span className="pulse" />LIVE{premium && match.clock != null && ` ${match.clock}′`}</span>
        ) : status === 'upcoming' ? (
          <span className="slide-chip">{dayLabel(match.startsAt, now)} · {clockTime(match.startsAt)}</span>
        ) : (
          <span className="slide-chip">Full time</span>
        )}
        <span className="slide-chip">{competition}</span>
      </div>
      <div className="match-hero-score">
        <HeroTeam team={home} onNavigate={onNavigate} />
        <span className="slide-nums" aria-live={status === 'live' ? 'polite' : undefined}>
          {showScore ? (
            <>{match.score[0]}<i>–</i>{match.score[1]}</>
          ) : status === 'upcoming' ? (
            <span className="hero-kickoff">{clockTime(match.startsAt)}</span>
          ) : (
            <span className="hero-locked" title="Live score for premium members">vs</span>
          )}
        </span>
        <HeroTeam team={away} onNavigate={onNavigate} />
      </div>
      <p className="match-hero-venue">📍 {match.venue}</p>
      {status === 'live' && premium && (
        <span className={`conn conn--${liveStatus}`} role="status">
          <span className="conn-dot" />
          {liveStatus === 'open' ? 'Live · connected' : liveStatus === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'}
        </span>
      )}
    </div>
  )
}

function HeroTeam({ team, onNavigate }) {
  return (
    <button className="match-hero-team" onClick={() => onNavigate({ type: 'team', teamId: team.id })}>
      <TeamBadge team={team} size={64} />
      <span>{team.name}</span>
    </button>
  )
}

function Section({ id, title, children }) {
  return (
    <section className="section" aria-labelledby={id}>
      <div className="section-head"><h2 id={id}>{title}</h2></div>
      {children}
    </section>
  )
}

function PlayerList({ items, onNavigate }) {
  return (
    <ul className="result-list">
      {items.map(({ player, note }) => (
        <li className="result-row" key={player.id}>
          <button className="rr-main" onClick={() => onNavigate({ type: 'player', playerId: player.id })}>
            <span className="player-num" style={{ '--team': player.team.color }} aria-hidden="true">{player.number}</span>
            <span className="rr-text">
              <span className="rr-title">{player.name}</span>
              <span className="rr-sub">{player.position} · {player.team.name} — {note}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function HeadToHeadBlock({ h2h, match, now }) {
  if (!h2h.played) return <p className="empty">These teams haven’t met yet.</p>
  return (
    <>
      <div className="h2h-summary">
        <div><strong>{h2h.homeWins}</strong><span>{match.home.short} wins</span></div>
        <div><strong>{h2h.draws}</strong><span>Draws</span></div>
        <div><strong>{h2h.awayWins}</strong><span>{match.away.short} wins</span></div>
      </div>
      <ul className="h2h-list">
        {h2h.matches.map((g) => (
          <li key={g.id}>
            <span className="h2h-date">{dayLabel(g.endedAt, now)}</span>
            <span className="h2h-game">{g.home.name} <strong>{g.score[0]}–{g.score[1]}</strong> {g.away.name}</span>
          </li>
        ))}
      </ul>
    </>
  )
}

function LiveTimeline({ events }) {
  const list = [...events].sort((a, b) => b.minute - a.minute || b.at - a.at)
  return (
    <ol className="timeline">
      {list.map((e) => (
        <li key={e.id} className={`tl tl--${e.kind}`}>
          <span className="tl-min">{e.minute}′</span>
          <span className="tl-icon" aria-hidden="true">{e.icon ?? KIND_ICON[e.kind]}</span>
          <span className="tl-text">
            {e.ai && <span className="ai-tag" title="Generated insight">AI insight</span>}
            {e.text}
          </span>
        </li>
      ))}
    </ol>
  )
}

function PremiumLock({ onNavigate, onSignIn, signedIn }) {
  return (
    <div className="premium-lock">
      <span className="lock-icon" aria-hidden="true">🔒</span>
      <div>
        <h2>Live is for premium members</h2>
        <p>Live matches are available for premium members. Ask your club for access.</p>
        <div className="lock-actions">
          <button className="btn btn--accent btn--sm" onClick={() => onNavigate({ type: 'account' })}>About Premium</button>
          {!signedIn && <button className="btn btn--ghost btn--sm" onClick={onSignIn}>Already a member? Log in</button>}
        </div>
      </div>
    </div>
  )
}

export default function MatchView({ matchId, matches, now, onNavigate }) {
  const { sportIcon } = useCatalog()
  const { me, requestLogin } = useMeContext()
  const premium = Boolean(me?.premium)
  // Reload the page data when the game changes state (kick-off, full time).
  const feedStatus = matches.find((m) => m.id === matchId)?.status ?? ''
  const detail = useLoad(() => api.match(matchId), `${matchId}:${premium}:${feedStatus}`)
  const stories = useLoad(() => api.matchStories(matchId), `${matchId}:${feedStatus}`)
  const d = detail.data
  const canConnect = Boolean(d && d.match.status === 'live' && d.access.liveAllowed)
  const live = useLiveMatch(matchId, canConnect)
  // The server can still refuse (e.g. Premium ended): fall back to the locked view.
  const liveAllowed = canConnect && live.status !== 'denied'

  if (detail.status === 'error' && !d) return <p className="empty">Match not found.</p>
  if (!d) return <p className="page-sub">Loading match…</p>

  const match = (liveAllowed && live.data?.match) || d.match
  const timeline = (liveAllowed && live.data?.timeline) || d.timeline || []
  const liveStakes = (liveAllowed && live.data?.liveStakes) || d.liveStakes
  const competition = `${sportIcon(match.sport)} ${d.tournamentName ?? match.league}${match.stage ? ` · ${match.stage}` : ''}`
  const story = (tag) => stories.data?.find((s) => s.tag === tag)

  return (
    <>
      {liveAllowed && live.status === 'reconnecting' && (
        <div className="notice notice--reconnect" role="status">Connection lost — reconnecting to the live feed…</div>
      )}
      {match.correction && <CorrectionBanner correction={match.correction} />}

      <MatchHeader
        match={match}
        competition={competition}
        now={now}
        premium={liveAllowed}
        liveStatus={live.status}
        onNavigate={onNavigate}
      />

      {match.status === 'upcoming' && (
        <>
          <Section id="stake-h" title="What’s at stake">
            {d.stakes?.length ? (
              <div className="scenario-grid">
                {d.stakes.map((c) => <ScenarioCard key={c.team.id} card={c} now={now} onNavigate={onNavigate} />)}
              </div>
            ) : (
              <p className="empty">A league game: a win is worth three points for either side.</p>
            )}
          </Section>
          {story('Preview') && (
            <Section id="preview-h" title="Preview">
              <StoryCard story={story('Preview')} now={now} onNavigate={onNavigate} />
            </Section>
          )}
          {d.playersToWatch?.length > 0 && (
            <Section id="watch-h" title="Players to watch"><PlayerList items={d.playersToWatch} onNavigate={onNavigate} /></Section>
          )}
          {d.headToHead && (
            <Section id="h2h-h" title="Head-to-head"><HeadToHeadBlock h2h={d.headToHead} match={match} now={now} /></Section>
          )}
        </>
      )}

      {d.junior && match.status !== 'live' && (
        <p className="st-legend junior-note">🛡 Junior game: player details are not shown, to protect young players.</p>
      )}

      {match.status === 'live' && !liveAllowed && (
        <PremiumLock onNavigate={onNavigate} onSignIn={() => requestLogin()} signedIn={Boolean(me?.signedIn)} />
      )}

      {match.status === 'live' && liveAllowed && (
        <>
          {liveStakes && <div className="stakes-banner" role="status"><span aria-hidden="true">⚖</span> {liveStakes}</div>}
          <Section id="tl-h" title="Live timeline">
            {timeline.length ? <LiveTimeline events={timeline} /> : <p className="empty">Waiting for the first events…</p>}
            <p className="st-legend">“AI insight” lines are generated automatically from the match data.</p>
          </Section>
        </>
      )}

      {match.status === 'finished' && (
        <>
          <div className="finished-actions">
            <ShareButton
              title={`${match.home.name} ${match.score[0]}–${match.score[1]} ${match.away.name}`}
              text={`${match.home.name} ${match.score[0]}–${match.score[1]} ${match.away.name}`}
              label="↗ Share result"
            />
          </div>
          {story('Match report') && (
            <Section id="report-h" title="Match report">
              <StoryCard story={story('Match report')} now={now} onNavigate={onNavigate} />
            </Section>
          )}
          {d.tableImpact && (
            <Section id="impact-h" title="Table impact">
              <ul className="impact">
                {d.tableImpact.map((i) => (
                  <li key={i.team.id}>
                    <TeamBadge team={i.team} size={28} />
                    <span><strong>{i.team.name}</strong> {i.text} in {i.groupName}</span>
                    <span className={`impact-arrow${i.before && i.after < i.before ? ' up' : i.before && i.after > i.before ? ' down' : ''}`}>
                      {i.before && i.after < i.before ? '▲' : i.before && i.after > i.before ? '▼' : '•'}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          {d.playerOfMatch && (
            <Section id="potm-h" title="Player of the match"><PlayerList items={[d.playerOfMatch]} onNavigate={onNavigate} /></Section>
          )}
        </>
      )}
    </>
  )
}
