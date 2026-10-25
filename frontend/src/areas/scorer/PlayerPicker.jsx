import { useState } from 'react'

const label = (p) => (p.name ? `#${p.number} ${p.name}` : `#${p.number}`)

/**
 * Bottom sheet after an event that needs a player: both rosters, searchable, recent players first,
 * the event's team before the other. Players without a public profile show as their number only.
 */
export default function PlayerPicker({ title, team, rosters, recent, exclude, optional, skipLabel, onPick, onSkip, onCancel }) {
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()
  const match = (p) => p.id !== exclude && (!query || String(p.number) === query || (p.name ?? '').toLowerCase().includes(query))
  const own = rosters[team] ?? []
  const other = rosters[team === 'home' ? 'away' : 'home'] ?? []
  const recentOwn = recent.map((id) => own.find((p) => p.id === id)).filter(Boolean)
  const rest = own.filter((p) => !recent.includes(p.id))
  const groups = [
    ['Recent', recentOwn.filter(match)],
    [rosters.names[team], rest.filter(match)],
    [`${rosters.names[team === 'home' ? 'away' : 'home']} (other team)`, query ? other.filter(match) : []],
  ].filter(([, list]) => list.length)

  return (
    <div className="sc-sheet-backdrop" onClick={onCancel}>
      <section className="sc-sheet" role="dialog" aria-modal="true" aria-labelledby="pick-h" onClick={(e) => e.stopPropagation()}>
        <div className="sc-sheet-head">
          <h2 id="pick-h">{title}</h2>
          <button className="sc-link" onClick={onCancel}>Cancel</button>
        </div>
        <input className="sc-search" type="search" inputMode="search" placeholder="Number or name" value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Search players" />
        <div className="sc-pick-list">
          {groups.map(([name, list]) => (
            <div key={name}>
              <h3>{name}</h3>
              <div className="sc-pick-grid">
                {list.map((p) => (
                  <button key={p.id} className="sc-pick" onClick={() => onPick(p.id)}>{label(p)}</button>
                ))}
              </div>
            </div>
          ))}
          {!groups.length && <p className="sc-muted">No player matches “{q}”.</p>}
        </div>
        {optional && <button className="sc-btn sc-btn--ghost" onClick={onSkip}>{skipLabel}</button>}
      </section>
    </div>
  )
}
