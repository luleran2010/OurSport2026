import { useCatalog } from '../../app/providers/catalog'
import { formatDateRange } from '../../utils/time'

export default function EventsView({ matches, onNavigate }) {
  const { tournaments, sportIcon, sportLabel, regionLabel } = useCatalog()
  const list = Object.values(tournaments).sort((a, b) => a.startsAt - b.startsAt)

  return (
    <>
      <div className="page-head">
        <h1>Events</h1>
        <p className="page-sub">Tournaments and cups around the north.</p>
      </div>
      {list.length ? (
        <div className="event-grid">
          {list.map((t) => {
            const live = matches.filter((m) => m.tournamentId === t.id && m.status === 'live').length
            return (
              <button key={t.id} className="event-card" onClick={() => onNavigate({ type: 'event', eventId: t.id })}>
                <span className="event-card-top">
                  <span className="sport-tag">{sportIcon(t.sport)} {sportLabel(t.sport)}</span>
                  {live > 0 && <span className="live-pill"><span className="pulse" />{live} LIVE</span>}
                </span>
                <strong className="event-card-name">{t.name}</strong>
                <span className="page-sub">{formatDateRange(t.startsAt, t.endsAt)} · {t.venue}</span>
                <span className="page-sub">Organised by {t.organiser.name} · {regionLabel(t.region)}</span>
              </button>
            )
          })}
        </div>
      ) : (
        <p className="empty">No events right now.</p>
      )}
    </>
  )
}
