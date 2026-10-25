import { useState } from 'react'
import { api } from '../../../api/client'
import { Notice } from './shared'
import { STAGE, sourceLabel, teamName, useAction } from './setup'

// Step 4: the engine's draw (pots, reasons, the seed anyone can replay) and schedule
// (days × pitches). Redraw, re-plan, or move one match; the engine re-checks every rule.

const side = (setup, key, source) => (key ? teamName(setup, key) : sourceLabel(source))

function Quality({ q }) {
  if (!q) return null
  const items = [
    q.hard_violations === 0 ? '✓ Every rule kept' : `⚠ ${q.hard_violations} rule(s) broken`,
    q.min_rest_minutes != null && `Shortest rest ${q.min_rest_minutes} min`,
    q.max_idle_minutes != null && `Longest wait ${q.max_idle_minutes} min`,
    q.group_stage_last_day != null && `Groups finish on day ${q.group_stage_last_day}`,
    q.final_in_best_slot && 'Final on the main pitch, last slot',
  ].filter(Boolean)
  return <div className="chip-row setup-quality">{items.map((t) => <span key={t} className="pub-status pub-status--info">{t}</span>)}</div>
}

function MovePanel({ setup, match, onMoved, onClose }) {
  const days = setup.draft.draft.schedule?.days ?? []
  const pitches = setup.draft.draft.schedule?.pitches ?? []
  const [f, setF] = useState({ date: match.local_date, start: match.local_time, pitch: match.pitch })
  const action = useAction(onMoved, async () => {})
  const move = (e) => {
    e.preventDefault()
    action.run(() => api.moveSetupMatch(setup.id, match.code, { date: f.date, start: f.start, pitch: f.pitch }))
  }
  return (
    <form className="profile-card setup-move" onSubmit={move}>
      <h3>Move {match.code}: {side(setup, match.home, match.home_source)} – {side(setup, match.away, match.away_source)}</h3>
      <div className="field-row field-row--3">
        <label className="field"><span>Day</span>
          <select value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })}>
            {days.map((d) => <option key={d.date} value={d.date}>{d.date}</option>)}
          </select>
        </label>
        <label className="field"><span>Kick-off</span>
          <input type="time" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />
        </label>
        <label className="field"><span>Pitch</span>
          <select value={f.pitch} onChange={(e) => setF({ ...f, pitch: e.target.value })}>
            {pitches.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
      </div>
      <p className="hint">The rest of the schedule is rebuilt around this match; rest times and pitch use are checked again.</p>
      <Notice action={action} />
      <div className="wiz-nav">
        <button type="button" className="btn btn--ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn--accent" disabled={action.busy}>{action.busy ? 'Re-planning…' : 'Move it'}</button>
      </div>
    </form>
  )
}

function ScheduleGrid({ setup, onPick }) {
  const matches = setup.schedule.matches
  const pitches = [...new Set(matches.map((m) => m.pitch))]
  const days = [...new Set(matches.map((m) => m.local_date))]
  return days.map((day, i) => {
    const today = matches.filter((m) => m.local_date === day)
    const times = [...new Set(today.map((m) => m.local_time))].sort()
    return (
      <section key={day} className="setup-day-plan">
        <h3 className="group-label">Day {i + 1} · {day}</h3>
        <div className="table-scroll">
          <table className="setup-grid">
            <thead><tr><th scope="col">Time</th>{pitches.map((p) => <th key={p} scope="col">{p}</th>)}</tr></thead>
            <tbody>
              {times.map((time) => (
                <tr key={time}>
                  <th scope="row">{time}</th>
                  {pitches.map((p) => {
                    const m = today.find((x) => x.local_time === time && x.pitch === p)
                    return (
                      <td key={p}>
                        {m && (
                          <button className={`setup-match setup-match--${m.stage}`} onClick={() => onPick(m)} title="Move this match">
                            <span className="setup-match-code">{m.code} · {m.group ? `Group ${m.group}` : STAGE[m.stage] ?? m.stage}</span>
                            <span>{side(setup, m.home, m.home_source)}</span>
                            <span>{side(setup, m.away, m.away_source)}</span>
                          </button>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    )
  })
}

export default function DrawStep({ setup, reload, onChange, onBack, onNext }) {
  const [moving, setMoving] = useState(null)
  const [confirmRedraw, setConfirmRedraw] = useState(false)
  const action = useAction(onChange, reload)
  const locked = setup.status === 'published'
  const draw = setup.draw
  const redraw = async () => {
    setConfirmRedraw(false)
    await action.run(() => api.redrawSetup(setup.id), 'A new draw with a new seed. The schedule was planned again.')
  }
  const replan = () => action.run(() => api.regenerateSchedule(setup.id), 'The schedule was planned again.')

  return (
    <div className="wiz-card setup-draw">
      {draw && (
        <section className="profile-card">
          <div className="section-head">
            <h2>The draw</h2>
            {!locked && (confirmRedraw ? (
              <span className="chip-row">
                <span className="hint">Draw again with a new seed?</span>
                <button className="btn btn--accent btn--sm" disabled={action.busy} onClick={redraw}>Yes, redraw</button>
                <button className="btn btn--ghost btn--sm" onClick={() => setConfirmRedraw(false)}>Keep this one</button>
              </span>
            ) : <button className="btn btn--ghost btn--sm" onClick={() => setConfirmRedraw(true)}>↻ Redraw</button>)}
          </div>
          <div className="wiz-group-cols">
            {draw.groups.map((g) => (
              <div key={g.group} className="wiz-group">
                <h3>{draw.groups.length > 1 ? `Group ${g.group}` : 'League'}</h3>
                <ul>
                  {g.teams.map((t) => (
                    <li key={t.key} className="setup-drawn" title={t.reason}>
                      {t.pot != null && <span className="setup-pot">Pot {t.pot}</span>}
                      <span>{t.name}</span>
                      <span className="hint">{t.reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="hint">Seed <code>{draw.seed}</code> · anyone can repeat this draw from the seed and the rules.</p>
        </section>
      )}

      <section className="profile-card">
        <div className="section-head">
          <h2>The schedule</h2>
          {!locked && setup.schedule && <button className="btn btn--ghost btn--sm" disabled={action.busy} onClick={replan}>↻ Plan again</button>}
        </div>
        {setup.schedule ? (
          <>
            <Quality q={setup.schedule.quality} />
            {moving && !locked && (
              <MovePanel setup={setup} match={moving} onClose={() => setMoving(null)}
                onMoved={(s) => { setMoving(null); onChange(s) }} />
            )}
            <ScheduleGrid setup={setup} onPick={(m) => !locked && setMoving(m)} />
            {!locked && <p className="hint">Click a match to move it.</p>}
          </>
        ) : (
          <p className="empty">No schedule yet — answer the open questions on the Review step.</p>
        )}
      </section>

      <Notice action={action} />
      <div className="wiz-nav">
        <button className="btn btn--ghost" onClick={onBack}>← Review</button>
        <button className="btn btn--accent" disabled={!['ready', 'published'].includes(setup.status)} onClick={onNext}>Next: publish →</button>
      </div>
    </div>
  )
}
