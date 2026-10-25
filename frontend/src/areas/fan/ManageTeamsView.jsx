import { useState } from 'react'
import TeamBadge from '../../components/TeamBadge'
import { useCatalog } from '../../app/providers/catalog'

export default function ManageTeamsView({ follow, onNavigate }) {
  const { sports, teams: allTeams } = useCatalog()
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()
  const teams = Object.values(allTeams).filter(
    (t) => !query || t.name.toLowerCase().includes(query) || t.league.toLowerCase().includes(query),
  )

  return (
    <>
      <div className="page-head">
        <h1>My teams</h1>
        <p className="page-sub">
          Following {follow.followed.length} team{follow.followed.length === 1 ? '' : 's'} — they appear in your sidebar and the “My teams” activity tab.
        </p>
      </div>

      <label className="search search--block">
        <span className="visually-hidden">Find a team</span>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a team or league" />
      </label>

      {sports.filter((s) => s.id !== 'all').map((s) => {
        const list = teams.filter((t) => t.sport === s.id)
        if (!list.length) return null
        return (
          <section className="section" key={s.id}>
            <h3 className="group-label">{s.icon} {s.label}</h3>
            <ul className="team-grid">
              {list.map((t) => {
                const on = follow.isFollowed(t.id)
                return (
                  <li className={`team-card${on ? ' is-on' : ''}`} key={t.id}>
                    <button className="team-card-main" onClick={() => onNavigate({ type: 'team', teamId: t.id })}>
                      <TeamBadge team={t} size={36} />
                      <span>
                        <span className="team-card-name">{t.name}</span>
                        <span className="team-card-league">{t.league}</span>
                      </span>
                    </button>
                    <button
                      className={`btn btn--sm ${on ? 'btn--ghost' : 'btn--accent'}`}
                      aria-pressed={on}
                      aria-label={`${on ? 'Unfollow' : 'Follow'} ${t.name}`}
                      onClick={() => follow.toggle(t.id)}
                    >
                      {on ? 'Following' : 'Follow'}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
      {!teams.length && <p className="empty">No teams match “{q}”.</p>}
    </>
  )
}
