import TeamBadge from '../../components/TeamBadge'
import MatchList from '../../components/MatchList'
import ScenarioCard from '../../components/ScenarioCard'
import StandingsTable from '../../components/StandingsTable'
import PlayerSpotlight from '../../components/PlayerSpotlight'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { timeAgo } from '../../utils/time'

const ORDER = { live: 0, upcoming: 1, finished: 2 }

/** Team page (F4): header, scenario, fixtures and results, standings, players to watch. */
export default function TeamView({ teamId, matches, now, follow, onNavigate }) {
  const { teams, clubs, sportIcon, sportLabel } = useCatalog()
  const { me } = useMeContext()
  const signedIn = Boolean(me?.signedIn)

  const teamMatches = matches
    .filter((m) => m.home.id === teamId || m.away.id === teamId)
    .sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.startsAt ?? -a.endedAt) - (b.startsAt ?? -b.endedAt))
  // Scenario and table change when one of the team's games finishes; who's signed in changes the players.
  const finished = teamMatches.filter((m) => m.status === 'finished').length
  const state = useLoad(() => api.teamPage(teamId), `${teamId}:${signedIn}:${me?.email ?? ''}:${me?.family?.length ?? 0}:${finished}`)

  const page = state.data
  const team = page?.team ?? teams[teamId]
  if (!team) {
    if (state.status === 'error' && state.error?.status === 404) return <p className="empty">Team not found.</p>
    if (state.status === 'error') return <p className="empty">Couldn’t load this team right now.</p>
    return <p className="page-sub">Loading team…</p>
  }
  const clubName = page?.clubName ?? clubs[team.clubId]?.name
  const following = follow.isFollowed(teamId)

  return (
    <>
      <div className="team-hero" style={{ '--team': team.color }}>
        <TeamBadge team={team} size={64} />
        <div className="team-hero-text">
          <h1>{team.name}</h1>
          <p className="page-sub">
            {sportIcon(team.sport)} {sportLabel(team.sport)}
            {page && <> · {page.ageGroupLabel}</>} · {team.league}
          </p>
          {clubName && (
            <button className="link-btn" onClick={() => onNavigate({ type: 'club', clubId: team.clubId })}>
              Part of {clubName} ›
            </button>
          )}
        </div>
        <button
          className={`btn ${following ? 'btn--ghost' : 'btn--accent'}`}
          aria-pressed={following}
          onClick={() => follow.toggle(teamId)}
        >
          {following ? '✓ Following' : '＋ Follow'}
        </button>
      </div>

      <TeamApiSections state={state} teamId={teamId} now={now} onNavigate={onNavigate} part="scenario" />

      <section className="section" aria-labelledby="tm-h">
        <div className="section-head"><h2 id="tm-h">Fixtures and results</h2></div>
        <MatchList
          matches={teamMatches}
          now={now}
          followed={follow.followed}
          onTeam={(id) => onNavigate({ type: 'team', teamId: id })}
          onOpen={(matchId) => onNavigate({ type: 'match', matchId })}
          empty="No games scheduled."
        />
      </section>

      <TeamApiSections state={state} teamId={teamId} now={now} onNavigate={onNavigate} part="rest" />
    </>
  )
}

/** The sections that come from GET /teams/{id}: the scenario (top), then standings and players to watch. */
function TeamApiSections({ state, teamId, now, onNavigate, part }) {
  if (state.status === 'error') {
    return part === 'scenario' ? <p className="empty">Couldn’t load the table and scenarios right now.</p> : null
  }
  const page = state.data
  if (!page) return part === 'scenario' ? <p className="page-sub">Loading…</p> : null
  const { competition, scenario, standings, playersToWatch, junior } = page

  if (part === 'scenario') {
    return (
      <section className="section" aria-labelledby="tsc-h">
        <div className="section-head">
          <h2 id="tsc-h">{competition ? competition.name : 'Competition'}</h2>
          {competition && (
            <button className="link-btn" onClick={() => onNavigate({ type: 'event', eventId: competition.id })}>
              Event page ›
            </button>
          )}
        </div>
        {scenario ? (
          <ScenarioCard card={scenario} now={now} onNavigate={onNavigate} />
        ) : (
          <p className="empty">
            {competition ? 'No scenario for this team yet.' : 'This team isn’t in a competition with a table right now.'}
          </p>
        )}
      </section>
    )
  }

  return (
    <>
      {standings && (
        <section className="section" aria-labelledby="tst-h">
          <div className="section-head">
            <h2 id="tst-h">Standings</h2>
            <span className="page-sub">Updated {timeAgo(standings.updatedAt, now)}</span>
          </div>
          <StandingsTable group={standings.group} data={standings} onNavigate={onNavigate} highlightTeamId={teamId} />
          <p className="st-legend">
            {standings.qualifyCount > 0 ? `Top ${standings.qualifyCount} go through · ` : ''}{standings.tiebreak.label} = {standings.tiebreak.description}.
          </p>
        </section>
      )}

      <section className="section" aria-labelledby="tpw-h">
        <div className="section-head"><h2 id="tpw-h">Players to watch</h2></div>
        {playersToWatch.length ? (
          <div className="spotlight-grid">
            {playersToWatch.map((s) => <PlayerSpotlight key={s.player.id} spot={s} onNavigate={onNavigate} />)}
          </div>
        ) : (
          <p className="empty">
            {junior
              ? 'Players aren’t featured for junior teams, to protect young players.'
              : 'No players to show for this team.'}
          </p>
        )}
      </section>
    </>
  )
}
