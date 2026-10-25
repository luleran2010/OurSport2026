import { useState } from 'react'
import { api } from '../../../api/client'
import { clockTime, dayLabel, formatWeekday, fromZonedInput, toZonedInput } from '../../../utils/time'

const FILTERS = [
  ['all', 'All'], ['upcoming', 'Upcoming'], ['result', 'Results to enter'], ['live', 'Live'], ['finished', 'Finished'], ['noscorer', 'No scorer'],
]
const STATUS = { upcoming: 'Upcoming', awaiting_result: 'Result due', live: 'Live', finished: 'Finished' }

function keep(r, f) {
  if (f === 'upcoming') return r.status === 'upcoming'
  if (f === 'result') return r.status === 'awaiting_result'
  if (f === 'live') return r.status === 'live'
  if (f === 'finished') return r.status === 'finished'
  if (f === 'noscorer') return (r.status === 'upcoming' || r.status === 'live') && r.match.dataLevel === 'live' && !r.scorer
  return true
}

function ScoreForm({ r, onSave, onCancel, busy }) {
  const [s, setS] = useState(r.match.score ? r.match.score.map(String) : ['', ''])
  const ok = s.every((x) => /^\d{1,3}$/.test(x))
  return (
    <form className="ev-inline" onSubmit={(e) => { e.preventDefault(); if (ok) onSave(s.map(Number)) }}>
      <span>{r.match.home.short}</span>
      <input aria-label={`${r.match.home.name} score`} inputMode="numeric" value={s[0]} onChange={(e) => setS([e.target.value, s[1]])} autoFocus />
      <span>–</span>
      <input aria-label={`${r.match.away.name} score`} inputMode="numeric" value={s[1]} onChange={(e) => setS([s[0], e.target.value])} />
      <span>{r.match.away.short}</span>
      <button className="btn btn--accent btn--sm" disabled={!ok || busy}>{r.status === 'finished' ? 'Save correction' : 'Save result'}</button>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>Cancel</button>
      {r.status === 'finished' && <span className="ev-sub">Fans see a “result corrected” note.</span>}
    </form>
  )
}

function EditForm({ r, venues, onSave, onCancel, busy }) {
  const [f, setF] = useState({ at: toZonedInput(r.match.startsAt), venue: r.match.venue, dataLevel: r.match.dataLevel })
  return (
    <form className="ev-inline" onSubmit={(e) => {
      e.preventDefault()
      onSave({ startsAt: fromZonedInput(f.at), venue: f.venue, dataLevel: f.dataLevel })
    }}>
      <label className="ev-mini"><span>Start</span><input type="datetime-local" value={f.at} onChange={(e) => setF({ ...f, at: e.target.value })} required /></label>
      <label className="ev-mini"><span>Venue</span><input list="ev-venues" value={f.venue} onChange={(e) => setF({ ...f, venue: e.target.value })} required minLength={2} /></label>
      <label className="ev-mini"><span>Data</span>
        <select value={f.dataLevel} onChange={(e) => setF({ ...f, dataLevel: e.target.value })}>
          <option value="live">Live (scorer)</option><option value="results_only">Results only</option>
        </select>
      </label>
      <datalist id="ev-venues">{venues.map((v) => <option key={v} value={v} />)}</datalist>
      <button className="btn btn--accent btn--sm" disabled={busy}>Save</button>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>Cancel</button>
    </form>
  )
}

function AddFixture({ d, eventId, onDone }) {
  const [f, setF] = useState({ home: '', away: '', at: '', venue: d.venue, stage: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await api.addEventMatch(eventId, { home: f.home, away: f.away, startsAt: fromZonedInput(f.at), venue: f.venue, group: f.stage || null })
      onDone('Fixture added.')
    } catch (x) {
      setErr(x.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="ev-card ev-add" onSubmit={submit}>
      <h3>Add a fixture</h3>
      <div className="ev-add-row">
        <label className="field"><span>Home</span>
          <select value={f.home} onChange={(e) => setF({ ...f, home: e.target.value })} required>
            <option value="">Pick a team</option>{d.teams.map((t) => <option key={t.team.id} value={t.team.id}>{t.team.name}</option>)}
          </select>
        </label>
        <label className="field"><span>Away</span>
          <select value={f.away} onChange={(e) => setF({ ...f, away: e.target.value })} required>
            <option value="">Pick a team</option>{d.teams.filter((t) => t.team.id !== f.home).map((t) => <option key={t.team.id} value={t.team.id}>{t.team.name}</option>)}
          </select>
        </label>
        <label className="field"><span>Start (Finnish time)</span><input type="datetime-local" value={f.at} onChange={(e) => setF({ ...f, at: e.target.value })} required /></label>
        <label className="field"><span>Venue</span><input list="ev-venues-add" value={f.venue} onChange={(e) => setF({ ...f, venue: e.target.value })} required minLength={2} /></label>
        <label className="field"><span>Stage <small>(for games across groups)</small></span>
          <input value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })} placeholder="e.g. Semi-final" maxLength={40} />
        </label>
        <datalist id="ev-venues-add">{d.venues.map((v) => <option key={v} value={v} />)}</datalist>
      </div>
      {err && <p className="form-error" role="alert">{err}</p>}
      <div className="ev-actions-row">
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => onDone(null)}>Cancel</button>
        <button className="btn btn--accent btn--sm" disabled={busy}>{busy ? 'Adding…' : 'Add fixture'}</button>
      </div>
    </form>
  )
}

export default function FixturesTab({ d, eventId, reload, filter, setTab }) {
  const [open, setOpen] = useState(null) // {id, mode: score|edit|remove}
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const now = d.updatedAt
  const rows = d.matches.filter((r) => keep(r, filter))
  const scorers = d.scorers.filter((s) => s.status !== 'expired')

  const run = async (fn, ok) => {
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setOpen(null)
      setMsg({ tone: 'ok', text: ok })
      reload()
    } catch (x) {
      setMsg({ tone: 'error', text: x.message })
    } finally {
      setBusy(false)
    }
  }

  // group by day
  const days = []
  for (const r of rows) {
    const key = dayLabel(r.match.startsAt ?? r.match.endedAt, now)
    const last = days[days.length - 1]
    if (last?.key === key) last.rows.push(r)
    else days.push({ key, ts: r.match.startsAt ?? r.match.endedAt, rows: [r] })
  }

  return (
    <div className="ev-fixtures">
      <div className="ev-toolbar">
        <div className="chips" role="group" aria-label="Show">
          {FILTERS.map(([id, label]) => {
            const n = d.matches.filter((r) => keep(r, id)).length
            return (
              <button key={id} className={`chip chip--sm${filter === id ? ' is-active' : ''}`} aria-pressed={filter === id}
                onClick={() => setTab('fixtures', id === 'all' ? {} : { show: id })}>
                {label} <span className="chip-count">{n}</span>
              </button>
            )
          })}
        </div>
        {!adding && <button className="btn btn--accent btn--sm" onClick={() => setAdding(true)}>+ Add fixture</button>}
      </div>
      {adding && <AddFixture d={d} eventId={eventId} onDone={(text) => { setAdding(false); if (text) { setMsg({ tone: 'ok', text }); reload() } }} />}
      {msg && <p className={msg.tone === 'error' ? 'form-error' : 'ev-ok'} role="status">{msg.text}</p>}
      {rows.length === 0 && <p className="placeholder">No matches here.</p>}
      {days.map((day) => (
        <section key={day.key + day.ts} className="ev-day">
          <h3 className="ev-day-h">{day.key}{day.ts && ['Today', 'Tomorrow', 'Yesterday'].includes(day.key) ? ` · ${formatWeekday(day.ts)}` : ''}</h3>
          <ul className="ev-matches">
            {day.rows.map((r) => {
              const m = r.match
              const o = open?.id === m.id ? open.mode : null
              return (
                <li key={m.id} className={`ev-match ev-match--${r.status}`}>
                  <div className="ev-match-row">
                    <span className="ev-time">
                      <b>{m.startsAt ? clockTime(m.startsAt) : m.endedAt ? clockTime(m.endedAt) : '–'}</b>
                      <span className="ev-sub">{!m.startsAt && m.endedAt ? `ended · ${r.group}` : r.group}</span>
                    </span>
                    <span className="ev-teams">
                      <b>{m.home.name}</b> {m.score ? <span className="ev-score">{m.score[0]}–{m.score[1]}</span> : <span className="ev-vs">v</span>} <b>{m.away.name}</b>
                      <span className="ev-sub">{m.venue}{m.correction ? ' · result corrected' : ''}</span>
                    </span>
                    <span className={`ev-state ev-state--${r.status}`}>{r.status === 'live' && <span className="live-dot" aria-hidden="true" />}{STATUS[r.status]}{r.status === 'live' && m.period ? ` · ${m.period}` : ''}</span>
                    <span className="ev-data">{m.dataLevel === 'live' ? 'Live data' : 'Results only'}</span>
                    <label className="ev-scorer">
                      <span className="sr-only">Scorer for {m.home.name} v {m.away.name}</span>
                      <select value={r.scorer?.memberId ?? ''} disabled={busy || r.status === 'finished' || m.dataLevel !== 'live'}
                        onChange={(e) => run(() => api.patchMatch(m.id, { scorerId: e.target.value || null }), e.target.value ? 'Scorer assigned.' : 'Scorer removed.')}>
                        <option value="">{m.dataLevel === 'live' ? (r.status === 'finished' ? '—' : 'No scorer') : 'Not needed'}</option>
                        {scorers.map((s) => <option key={s.id} value={s.id}>{s.name ?? s.email}{s.status === 'invited' ? ' (invited)' : ''}</option>)}
                        {r.scorer && !scorers.some((s) => s.id === r.scorer.memberId) && <option value={r.scorer.memberId}>{r.scorer.name}</option>}
                      </select>
                    </label>
                    <span className="ev-row-actions">
                      {r.canFinish && r.status !== 'finished' && <button className="btn btn--accent btn--sm" onClick={() => setOpen({ id: m.id, mode: 'score' })}>Enter result</button>}
                      {r.status === 'finished' && <button className="btn btn--ghost btn--sm" onClick={() => setOpen({ id: m.id, mode: 'score' })}>Correct result</button>}
                      {r.editable && !r.canFinish && <button className="btn btn--ghost btn--sm" onClick={() => setOpen({ id: m.id, mode: 'edit' })}>Edit</button>}
                      {r.editable && !r.canFinish && r.eventsRecorded === 0 && (
                        <button className="btn btn--ghost btn--sm ev-danger" onClick={() => setOpen({ id: m.id, mode: 'remove' })}>Remove</button>
                      )}
                    </span>
                  </div>
                  {o === 'score' && <ScoreForm r={r} busy={busy} onCancel={() => setOpen(null)}
                    onSave={(score) => run(() => api.patchMatch(m.id, { score }), r.status === 'finished' ? 'Result corrected.' : 'Result saved. Fans get it now.')} />}
                  {o === 'edit' && <EditForm r={r} venues={d.venues} busy={busy} onCancel={() => setOpen(null)}
                    onSave={(patch) => run(() => api.patchMatch(m.id, patch), 'Fixture updated.')} />}
                  {o === 'remove' && (
                    <div className="ev-inline">
                      <span>Remove {m.home.name} v {m.away.name}? Its preview is removed too.</span>
                      <button className="btn btn--danger btn--sm" disabled={busy} onClick={() => run(() => api.deleteMatch(m.id), 'Fixture removed.')}>Remove</button>
                      <button className="btn btn--ghost btn--sm" onClick={() => setOpen(null)}>Cancel</button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
