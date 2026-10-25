export default function TeamsTab({ d, onNavigate }) {
  return (
    <div className="ev-groups">
      {d.groups.map((g) => {
        const rows = d.teams.filter((t) => t.group === g.name).sort((a, b) => (a.position ?? 99) - (b.position ?? 99))
        return (
          <section key={g.id} className="ev-card">
            <h2 className="ev-h2">{g.name}</h2>
            <table className="ev-table">
              <thead><tr><th>#</th><th>Team</th><th>Club</th><th className="num">Played</th><th className="num">Points</th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.team.id}>
                    <td>{t.position ?? '–'}</td>
                    <td>
                      <span className="team-dot" style={{ background: t.team.color }} aria-hidden="true" />{' '}
                      <button className="link-btn" onClick={() => onNavigate({ type: 'team', teamId: t.team.id })}>{t.team.name}</button>
                    </td>
                    <td className="ev-sub">{t.clubName ?? '—'}</td>
                    <td className="num">{t.played}</td>
                    <td className="num"><b>{t.points}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
      <p className="page-sub">Teams and groups are fixed once the event is published. Ask OurSport if a team withdraws.</p>
    </div>
  )
}
