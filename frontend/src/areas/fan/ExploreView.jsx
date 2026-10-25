import { useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import Icon from '../../components/Icon'
import MatchRow from '../../components/MatchRow'
import SuggestClubDialog from './components/explore/SuggestClubDialog'
import { ClubRow, PlayerRow, TeamRow } from './components/explore/ResultRows'
import { useCatalog } from '../../app/providers/catalog'
import { api } from '../../api/client'

const GROUPS = [
  { key: 'clubs', label: 'Clubs' },
  { key: 'teams', label: 'Teams' },
  { key: 'events', label: 'Events' },
  { key: 'players', label: 'Players' },
]
const PREVIEW = 5

function ChipRow({ label, options, value, onChange }) {
  return (
    <div className="filter-row" role="group" aria-label={label}>
      <span className="filter-label">{label}</span>
      <div className="chips">
        {options.map((o) => {
          const active = (value || 'all') === o.id
          return (
            <button
              key={o.id}
              className={`chip chip--sm${active ? ' is-active' : ''}`}
              aria-pressed={active}
              onClick={() => onChange(active && o.id !== 'all' ? 'all' : o.id)}
            >
              {o.icon && <span aria-hidden="true">{o.icon}</span>}
              {o.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function ExploreView({ follow, onNavigate, now }) {
  const { types, sports, regions, ageGroups } = useCatalog()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  // Keep the navigation state (App keys this view on it) while editing the URL.
  const replace = { replace: true, state: location.state }
  const q = params.get('q') ?? ''
  const type = params.get('type') ?? 'all'
  const sport = params.get('sport') ?? ''
  const region = params.get('region') ?? ''
  const age = params.get('age') ?? ''

  const [text, setText] = useState(q)
  const [result, setResult] = useState({ status: 'loading', data: null })
  const [suggestOpen, setSuggestOpen] = useState(false)

  const setParam = (patch) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(patch)) {
          if (!v || v === 'all') p.delete(k)
          else p.set(k, v)
        }
        return p
      },
      replace,
    )

  useEffect(() => {
    const ctrl = new AbortController()
    const id = setTimeout(() => {
      setResult((r) => ({ ...r, status: 'loading' }))
      api
        .search({ q, type, sport, region, age, limit: type === 'all' ? PREVIEW : 50 }, ctrl.signal)
        .then((data) => setResult({ status: 'ready', data }))
        .catch((err) => err.name !== 'AbortError' && setResult({ status: 'error', data: null, error: err }))
    }, 200)
    return () => {
      clearTimeout(id)
      ctrl.abort()
    }
  }, [q, type, sport, region, age])

  const filtered = Boolean(q || sport || region || age || type !== 'all')
  const { data } = result

  return (
    <>
      <div className="page-head">
        <h1>Explore</h1>
        <p className="page-sub">Find clubs, teams, events and players around the north.</p>
      </div>

      <form className="explore-search" role="search" onSubmit={(e) => e.preventDefault()}>
        <span className="explore-search-icon"><Icon name="search" size={20} /></span>
        <label className="visually-hidden" htmlFor="explore-q">Search clubs, teams, events and players</label>
        <input
          id="explore-q"
          type="search"
          value={text}
          autoComplete="off"
          placeholder="Search clubs, teams, events, players"
          onChange={(e) => {
            setText(e.target.value)
            setParam({ q: e.target.value.trim() })
          }}
        />
      </form>

      <div className="filters">
        <ChipRow label="Show" options={types} value={type} onChange={(v) => setParam({ type: v })} />
        <ChipRow label="Sport" options={sports} value={sport} onChange={(v) => setParam({ sport: v })} />
        <ChipRow label="Region" options={[{ id: 'all', label: 'All' }, ...regions]} value={region} onChange={(v) => setParam({ region: v })} />
        <ChipRow label="Age group" options={[{ id: 'all', label: 'All' }, ...ageGroups]} value={age} onChange={(v) => setParam({ age: v })} />
        {filtered && (
          <button
            className="link-btn clear-filters"
            onClick={() => {
              setText('')
              setParams({}, replace)
            }}
          >
            Clear search and filters
          </button>
        )}
      </div>


      <div className="results" aria-live="polite" aria-busy={result.status === 'loading'}>
        {result.status === 'error' && <p className="empty">Search is unavailable right now. Please try again.</p>}

        {data && data.total === 0 && (
          <div className="no-results">
            <h2>No results{q ? <> for “{q}”</> : ''}</h2>
            <p>Check the spelling, try a shorter search or remove some filters.</p>
            <p>
              Can’t find your club?{' '}
              <button className="link-btn link-btn--accent" onClick={() => setSuggestOpen(true)}>Suggest a club</button>
            </p>
          </div>
        )}

        {data && data.total > 0 && (
          <>
            <p className="results-summary">
              {data.total} result{data.total === 1 ? '' : 's'}
              {q && <> for “{data.query}”</>}
              {result.status === 'loading' && <span className="results-updating"> · updating…</span>}
            </p>
            {GROUPS.map(({ key, label }) => {
              const items = data[key]
              const count = data.counts[key]
              if (!count) return null
              return (
                <section className="section result-group" key={key} aria-labelledby={`rg-${key}`}>
                  <div className="section-head">
                    <h2 id={`rg-${key}`}>{label} <span className="count">{count}</span></h2>
                    {type === 'all' && count > items.length && (
                      <button className="link-btn" onClick={() => setParam({ type: key })}>Show all {count}</button>
                    )}
                  </div>
                  {key === 'events' ? (
                    <ul className="match-list">
                      {items.map((m) => (
                        <MatchRow key={m.id} match={m} now={now} followed={follow.followed} onTeam={(teamId) => onNavigate({ type: 'team', teamId })} onOpen={(matchId) => onNavigate({ type: 'match', matchId })} />
                      ))}
                    </ul>
                  ) : (
                    <ul className="result-list">
                      {items.map((item) =>
                        key === 'clubs' ? (
                          <ClubRow key={item.id} club={item} follow={follow} onNavigate={onNavigate} />
                        ) : key === 'teams' ? (
                          <TeamRow key={item.id} team={item} follow={follow} onNavigate={onNavigate} />
                        ) : (
                          <PlayerRow key={item.id} player={item} follow={follow} onNavigate={onNavigate} />
                        ),
                      )}
                    </ul>
                  )}
                </section>
              )
            })}
            <p className="results-foot">
              Missing a club?{' '}
              <button className="link-btn link-btn--accent" onClick={() => setSuggestOpen(true)}>Suggest a club</button>
            </p>
          </>
        )}

        {!data && result.status === 'loading' && <p className="page-sub">Searching…</p>}
      </div>

      <SuggestClubDialog open={suggestOpen} onClose={() => setSuggestOpen(false)} initialName={q} />
    </>
  )
}
