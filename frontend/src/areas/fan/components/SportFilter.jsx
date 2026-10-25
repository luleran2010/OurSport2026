import { useCatalog } from '../../../app/providers/catalog'

export default function SportFilter({ value, onChange, liveCounts }) {
  const { sports } = useCatalog()
  return (
    <nav className="sport-filter" aria-label="Filter by sport">
      {sports.map((s) => {
        const count = liveCounts[s.id] ?? 0
        return (
          <button
            key={s.id}
            className={`chip${value === s.id ? ' is-active' : ''}`}
            aria-pressed={value === s.id}
            onClick={() => onChange(s.id)}
          >
            {s.icon && <span aria-hidden="true">{s.icon}</span>}
            {s.label}
            {count > 0 && <span className="chip-count">{count}</span>}
          </button>
        )
      })}
    </nav>
  )
}
