import TeamBadge from './TeamBadge'

/**
 * One group table from the standings API. `data` carries the labels (tiebreak, for/against) and the
 * qualify count; `highlightTeamId` marks one team's row (team page F4).
 */
export default function StandingsTable({ group, data, onNavigate, highlightTeamId }) {
  const { tiebreak, forLabel, againstLabel, qualifyCount } = data
  return (
    <section className="standings" aria-labelledby={`grp-${group.id}`}>
      <h3 className="group-label" id={`grp-${group.id}`}>{group.name}</h3>
      <div className="table-scroll">
        <table className="standings-table">
          <thead>
            <tr>
              <th scope="col" className="num">#</th>
              <th scope="col" className="team-col">Team</th>
              <th scope="col" className="num"><abbr title="Played">P</abbr></th>
              <th scope="col" className="num hide-sm"><abbr title="Won">W</abbr></th>
              <th scope="col" className="num hide-sm"><abbr title="Drawn">D</abbr></th>
              <th scope="col" className="num hide-sm"><abbr title="Lost">L</abbr></th>
              <th scope="col" className="num hide-sm">{forLabel}</th>
              <th scope="col" className="num hide-sm">{againstLabel}</th>
              <th scope="col" className="num"><abbr title={tiebreak.description}>{tiebreak.label}</abbr></th>
              <th scope="col" className="num"><abbr title="Points">Pts</abbr></th>
              <th scope="col" className="form-col">Form</th>
            </tr>
          </thead>
          <tbody>
            {group.rows.map((r) => (
              <tr
                key={r.team.id}
                className={`st-row st-row--${r.status}${r.position === qualifyCount ? ' st-cutoff' : ''}${r.team.id === highlightTeamId ? ' st-row--mine' : ''}`}
                aria-current={r.team.id === highlightTeamId ? 'true' : undefined}
              >
                <td className="num pos">{r.position}</td>
                <td className="team-col">
                  <button className="st-team" onClick={() => onNavigate({ type: 'team', teamId: r.team.id })}>
                    <TeamBadge team={r.team} size={22} />
                    <span>{r.team.name}</span>
                    {r.team.id === highlightTeamId && <span className="sr-only"> (this team)</span>}
                    {r.status !== 'alive' && (
                      <span className={`st-status st-status--${r.status}`}>{r.status === 'through' ? '✓' : '✕'}</span>
                    )}
                  </button>
                </td>
                <td className="num">{r.played}</td>
                <td className="num hide-sm">{r.won}</td>
                <td className="num hide-sm">{r.drawn}</td>
                <td className="num hide-sm">{r.lost}</td>
                <td className="num hide-sm">{r.scored}</td>
                <td className="num hide-sm">{r.conceded}</td>
                <td className="num">{r.tiebreakDisplay}</td>
                <td className="num pts">{r.points}</td>
                <td className="form-col">
                  <span className="form">
                    {r.form.map((f, i) => <span key={i} className={`form-pip form-pip--${f}`} title={f}>{f}</span>)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
