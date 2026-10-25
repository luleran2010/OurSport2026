import { useEffect, useEffectEvent, useState } from 'react'
import TeamBadge from '../../components/TeamBadge'
import { useMeContext } from '../../app/providers/me'
import { useCatalog } from '../../app/providers/catalog'
import { api } from '../../api/client'
import { useOnline } from '../../live/useOnline'
import { clockTime, dayLabel, formatDate } from '../../utils/time'
import { loadAssignments, pendingCounts, saveAssignments } from './offlineStore'

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Why the list didn't load, in the scorer's words (a pass works on the tournament days only). */
function errorText(err) {
  if (err?.code === 'pass_not_yet_valid') {
    const from = /\d{4}-\d\d-\d\dT[\d:.+-]+/.exec(err.message ?? '')?.[0]
    return `This scorer pass works on the tournament days only${from ? ` — from ${formatDate(Date.parse(from))}` : ''}. Open it again then.`
  }
  if (err?.code === 'pass_revoked') return 'This scorer pass has expired or was withdrawn. Ask the organiser for a new one.'
  if (err?.status === 401 || err?.status === 403) return 'You don’t have access to score here. Open the link from your scorer pass, or sign in.'
  return 'The server didn’t answer.'
}

/** The next state: fresh from the server (and saved on the device), or the saved copy when the network fails. */
async function fetchAssignments(email) {
  try {
    const data = await api.scoringAssignments()
    saveAssignments(email, data)
    return { status: 'ready', data, savedAt: Date.now() }
  } catch (err) {
    if (err.status === 401 || err.status === 403) return { status: 'error', data: null, error: err }
    const saved = loadAssignments(email)
    return saved ? { status: 'offline', data: saved.data, savedAt: saved.savedAt } : { status: 'error', data: null, error: err }
  }
}

/**
 * Loads the assignments; falls back to the copy saved on this device when the network fails.
 * state: { status: loading | ready | offline | error, data, savedAt }
 */
function useAssignments(email, online) {
  const [state, setState] = useState(() => {
    const saved = loadAssignments(email)
    return saved ? { status: 'loading', data: saved.data, savedAt: saved.savedAt } : { status: 'loading', data: null }
  })
  const [pending, setPending] = useState({})
  const [version, setVersion] = useState(0)

  const apply = useEffectEvent((next, counts) => {
    setPending(counts)
    setState(next)
  })
  useEffect(() => {
    let cancelled = false
    Promise.all([fetchAssignments(email), pendingCounts()]).then(([next, counts]) => !cancelled && apply(next, counts))
    return () => {
      cancelled = true
    }
  }, [email, version, online]) // load again when the connection comes back

  return { ...state, pending, reload: () => setVersion((v) => v + 1) }
}

function MatchCard({ a, pending, onStart }) {
  const { sportIcon } = useCatalog()
  const m = a.match
  const unsent = pending[m.id] ?? 0
  const live = m.status === 'live'
  return (
    <li className={`sc-card${live ? ' is-live' : ''}`}>
      <div className="sc-when">
        {live ? (
          <span className="sc-live">● LIVE{m.clock ? ` ${m.clock}′` : ''}</span>
        ) : (
          <span className="sc-time">{clockTime(m.startsAt)}</span>
        )}
        <span>{live ? 'Now' : dayLabel(m.startsAt, a.serverNow)}</span>
      </div>
      <div className="sc-teams">
        <span><TeamBadge team={m.home} size={28} /> {m.home.name}</span>
        <span><TeamBadge team={m.away} size={28} /> {m.away.name}</span>
      </div>
      {live && m.score && <div className="sc-score" aria-label={`Score ${m.score[0]} to ${m.score[1]}`}>{m.score[0]}–{m.score[1]}</div>}
      <p className="sc-meta">
        📍 {m.venue} · {sportIcon(m.sport)} {a.competition}
        {a.dataLevel === 'results_only' && <> · <strong>Result only</strong></>}
      </p>
      {unsent > 0 && <p className="sc-warn">⚠ {plural(unsent, 'event')} not sent yet</p>}
      {a.canStart ? (
        <button className="sc-btn" onClick={onStart}>
          {a.dataLevel === 'results_only' ? 'Enter result' : live || a.eventsRecorded ? 'Continue scoring' : 'Start scoring'}
        </button>
      ) : (
        <button className="sc-btn" disabled>Opens on match day</button>
      )}
    </li>
  )
}

function PastRow({ a, pending, onOpen }) {
  const m = a.match
  const unsent = pending[m.id] ?? 0
  return (
    <li>
      <button className="sc-past" onClick={onOpen}>
        <span className="sc-past-teams">
          <strong>{m.home.name} {m.score ? `${m.score[0]}–${m.score[1]}` : 'v'} {m.away.name}</strong>
          <span>{formatDate(m.endedAt ?? m.startsAt)} · {m.venue}</span>
        </span>
        {unsent > 0 ? (
          <span className="sc-sync sc-sync--warn">⚠ {plural(unsent, 'event')} not synced</span>
        ) : (
          <span className="sc-sync">✓ Synced{a.eventsRecorded ? ` · ${plural(a.eventsRecorded, 'event')}` : ''}</span>
        )}
      </button>
    </li>
  )
}

export default function MyMatchesView({ onNavigate }) {
  const { me } = useMeContext()
  const online = useOnline()
  const s = useAssignments(me?.email, online)
  const start = (matchId) => onNavigate({ type: 'scorer', matchId })

  if (!s.data) {
    if (s.status === 'error') {
      return (
        <section className="sc-panel" role="alert">
          <h1>Can’t load your matches</h1>
          <p>{!online ? 'You’re offline and this device has no saved list yet.' : errorText(s.error)}</p>
          <button className="sc-btn" onClick={s.reload}>Try again</button>
        </section>
      )
    }
    return <p className="sc-muted" aria-busy="true">Loading your matches…</p>
  }

  const d = s.data
  const withNow = (a) => ({ ...a, serverNow: d.updatedAt })
  const today = d.active.filter((a) => a.day === 'today').map(withNow)
  const later = d.active.filter((a) => a.day === 'later').map(withNow)
  const unsentTotal = Object.values(s.pending).reduce((x, y) => x + y, 0)

  return (
    <>
      <div className="sc-head">
        <h1>My matches</h1>
        <p className="sc-muted">{d.scorerName} · {d.clubs.map((c) => c.name).join(', ')}</p>
      </div>

      {s.status === 'offline' && (
        <div className="sc-banner sc-banner--offline" role="status">
          <strong>Offline.</strong> Showing the list saved on this phone at {clockTime(s.savedAt)}.
          <button className="sc-btn sc-btn--small" onClick={s.reload}>Retry</button>
        </div>
      )}
      {unsentTotal > 0 && (
        <div className="sc-banner sc-banner--warn" role="status">
          <strong>{plural(unsentTotal, 'event')} waiting to be sent.</strong> {online ? 'Open the match to send them.' : 'They are sent when you’re back online.'}
        </div>
      )}

      <section aria-labelledby="today-h">
        <h2 id="today-h" className="sc-h2">Today</h2>
        {today.length ? (
          <ul className="sc-list">{today.map((a) => <MatchCard key={a.match.id} a={a} pending={s.pending} onStart={() => start(a.match.id)} />)}</ul>
        ) : (
          <p className="sc-empty">No matches to score today.</p>
        )}
      </section>

      {later.length > 0 && (
        <section aria-labelledby="later-h">
          <h2 id="later-h" className="sc-h2">Coming up</h2>
          <ul className="sc-list">{later.map((a) => <MatchCard key={a.match.id} a={a} pending={s.pending} onStart={() => start(a.match.id)} />)}</ul>
        </section>
      )}

      <section aria-labelledby="past-h">
        <h2 id="past-h" className="sc-h2">Past matches</h2>
        {d.past.length ? (
          <ul className="sc-past-list">{d.past.map((a) => <PastRow key={a.match.id} a={a} pending={s.pending} onOpen={() => start(a.match.id)} />)}</ul>
        ) : (
          <p className="sc-empty">No past matches yet.</p>
        )}
      </section>
    </>
  )
}
