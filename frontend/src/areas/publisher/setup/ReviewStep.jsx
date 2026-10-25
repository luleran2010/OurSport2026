import { useState } from 'react'
import { api } from '../../../api/client'
import { Notice } from './shared'
import { STAGE, tiebreakers, useAction } from './setup'

// Step 3: what the AI read, what it assumed, and the questions only the organiser can answer.
// Answers and edits go to the backend, which re-validates, then draws and schedules.

const TIEBREAK_PRESETS = {
  football_gd_first: 'Goal difference first (leagues)',
  football_h2h_first: 'Matches between the tied teams first (short tournaments)',
}
const QUESTION_HINT = { 'schedule.days': '09:00-18:00', 'schedule.pitches': '4' }
const OPTION_LABEL = {
  'rules.tiebreakers': { 'goal difference': 'Points, then goal difference', 'head-to-head': 'Points, then the matches between the tied teams' },
}
const optionLabel = (field, o) => (field === 'schedule.match_minutes' ? `Use ${o} minutes per match` : OPTION_LABEL[field]?.[o] ?? o)

/** Minutes the time zone is ahead of UTC on that date (the engine plans in local time). */
function offsetMinutes(date, zone) {
  const noon = new Date(`${date}T12:00:00Z`)
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).formatToParts(noon)
  const get = (t) => Number(parts.find((p) => p.type === t).value)
  return Math.round((Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute')) - noon.getTime()) / 60000)
}

const hhmm = (t) => (t ?? '').slice(0, 5)

function datesBetween(first, last) {
  const out = []
  for (let d = new Date(`${first}T00:00:00Z`); d <= new Date(`${last ?? first}T00:00:00Z`) && out.length < 14;
    d = new Date(d.getTime() + 86400000)) {
    out.push(d.toISOString().slice(0, 10))
  }
  return out
}

/** When and where it's played: builds the engine's SchedulePolicy (changeSetupDraft field "schedule"). */
function ScheduleForm({ setup, onSaved, onCancel }) {
  const t = setup.tournament
  const draft = setup.draft.draft
  const current = draft.schedule
  const match = draft.rules.match ?? {}
  const [firstDate] = useState(() => current?.days[0]?.date ?? t.starts_on ?? new Date().toISOString().slice(0, 10))
  const [f, setF] = useState(() => ({
    days: current?.days.map((d) => ({ date: d.date, start: hhmm(d.start), end: hhmm(d.end) }))
      ?? datesBetween(firstDate, t.ends_on).map((date) => ({ date, start: '09:00', end: '18:00' })),
    pause: current?.days[0]?.blocked?.[0] ? `${hhmm(current.days[0].blocked[0][0])}-${hhmm(current.days[0].blocked[0][1])}` : '',
    pitches: (current?.pitches ?? ['Pitch 1', 'Pitch 2']).join(', '),
    matchMinutes: current?.match_minutes ?? ((match.periods ?? 2) * (match.period_minutes ?? 20) + (match.half_time_minutes ?? 5)),
    breakMinutes: current?.break_minutes ?? 5,
    restMinutes: current?.min_rest_minutes ?? 60,
    perDay: current?.max_matches_per_team_per_day ?? 3,
  }))
  const action = useAction(onSaved, async () => {})
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const setDay = (i, k, v) => set('days', f.days.map((d, j) => (j === i ? { ...d, [k]: v } : d)))
  const pause = f.pause.trim() ? f.pause.split('-').map((x) => x.trim()) : null
  const pitches = f.pitches.split(',').map((p) => p.trim()).filter(Boolean)
  const invalid = !f.days.length || f.days.some((d) => !d.date || !d.start || !d.end || d.end <= d.start) || !pitches.length
    || (pause && (pause.length !== 2 || !/^\d\d:\d\d$/.test(pause[0]) || !/^\d\d:\d\d$/.test(pause[1])))

  const save = (e) => {
    e.preventDefault()
    const policy = {
      time_zone: t.time_zone,
      days: f.days.map((d) => ({
        date: d.date, start: d.start, end: d.end, utc_offset_minutes: offsetMinutes(d.date, t.time_zone),
        blocked: pause ? [pause] : [],
      })),
      pitches,
      match_minutes: Number(f.matchMinutes), break_minutes: Number(f.breakMinutes), min_rest_minutes: Number(f.restMinutes),
      max_matches_per_team_per_day: Number(f.perDay),
      simultaneous_last_group_round: current?.simultaneous_last_group_round ?? true,
      group_stage_ends_by_day: current?.group_stage_ends_by_day ?? null,
      fixed_slots: current?.fixed_slots ?? [],
      final_on_main_pitch_last_slot: current?.final_on_main_pitch_last_slot ?? true,
    }
    action.run(() => api.changeSetupDraft(setup.id, setup.draft.version, 'schedule', JSON.stringify(policy)))
  }

  return (
    <form className="setup-schedule-form" onSubmit={save}>
      <fieldset className="field">
        <legend>Days and playing times (local time, {t.time_zone})</legend>
        {f.days.map((d, i) => (
          <div key={i} className="setup-day">
            <input type="date" aria-label="Date" value={d.date} onChange={(e) => setDay(i, 'date', e.target.value)} />
            <input type="time" aria-label="First match" value={d.start} onChange={(e) => setDay(i, 'start', e.target.value)} />
            <span>–</span>
            <input type="time" aria-label="Last match ends" value={d.end} onChange={(e) => setDay(i, 'end', e.target.value)} />
            {f.days.length > 1 && <button type="button" className="link-btn" onClick={() => set('days', f.days.filter((_, j) => j !== i))}>Remove</button>}
          </div>
        ))}
        <button type="button" className="link-btn link-btn--accent" onClick={() => {
          const last = f.days[f.days.length - 1]
          const next = last ? new Date(Date.parse(`${last.date}T00:00:00Z`) + 86400000).toISOString().slice(0, 10) : firstDate
          set('days', [...f.days, { date: next, start: last?.start ?? '09:00', end: last?.end ?? '18:00' }])
        }}>+ Add a day</button>
      </fieldset>
      <div className="field-row">
        <label className="field"><span>Pitches (comma-separated, main pitch first)</span>
          <input value={f.pitches} onChange={(e) => set('pitches', e.target.value)} />
        </label>
        <label className="field"><span>Daily break, e.g. 13:00-13:30 (optional)</span>
          <input value={f.pause} onChange={(e) => set('pause', e.target.value)} placeholder="13:00-13:30" />
        </label>
      </div>
      <div className="field-row field-row--4">
        <label className="field"><span>Pitch time per match (min)</span>
          <input type="number" min={1} max={240} value={f.matchMinutes} onChange={(e) => set('matchMinutes', e.target.value)} />
        </label>
        <label className="field"><span>Changeover (min)</span>
          <input type="number" min={0} max={120} value={f.breakMinutes} onChange={(e) => set('breakMinutes', e.target.value)} />
        </label>
        <label className="field"><span>Rest between a team’s matches (min)</span>
          <input type="number" min={0} value={f.restMinutes} onChange={(e) => set('restMinutes', e.target.value)} />
        </label>
        <label className="field"><span>Matches per team per day</span>
          <input type="number" min={1} value={f.perDay} onChange={(e) => set('perDay', e.target.value)} />
        </label>
      </div>
      <Notice action={action} />
      <div className="wiz-nav">
        {onCancel ? <button type="button" className="btn btn--ghost" onClick={onCancel}>Cancel</button> : <span />}
        <button className="btn btn--accent" disabled={invalid || action.busy}>{action.busy ? 'Planning…' : 'Save and plan the schedule'}</button>
      </div>
    </form>
  )
}

function Question({ setup, q, onChange }) {
  const [value, setValue] = useState('')
  const action = useAction(onChange, async () => {})
  const answer = (v) => action.run(() => api.answerSetup(setup.id, setup.draft.version, [{ question_id: q.id, value: v }]))
  const needsSchedule = q.field === 'schedule.days' && !setup.draft.draft.schedule
  // engine validation issues (ref.issue): one tap when the backend offers the fix, else change the schedule
  const issue = Boolean(q.ref?.issue) && q.options.length === 0
  const [editing, setEditing] = useState(false)
  return (
    <li className={`setup-question setup-question--${q.impact}`}>
      <p><strong>{q.text}</strong>{q.impact === 'high' && <span className="pub-status pub-status--warn"> Needed to publish</span>}</p>
      {q.quotes.length > 0 && (
        <div className="setup-quotes">
          <span className="hint">From your documents:</span>
          {q.quotes.map((quote, i) => <blockquote key={i}>“{quote}”</blockquote>)}
        </div>
      )}
      {needsSchedule ? (
        <ScheduleForm setup={setup} onSaved={onChange} />
      ) : issue && q.field.startsWith('tiebreakers') ? (
        // a question stored before the backend offered the presets: the same fix as a draft change
        <div className="chip-row">
          {Object.entries(OPTION_LABEL['rules.tiebreakers']).map(([o, label]) => (
            <button key={o} className="btn btn--ghost btn--sm" disabled={action.busy}
              onClick={() => action.run(() => api.changeSetupDraft(setup.id, setup.draft.version, 'rules.tiebreakers', o))}>{label}</button>
          ))}
        </div>
      ) : issue ? (
        editing ? <ScheduleForm setup={setup} onSaved={onChange} onCancel={() => setEditing(false)} /> : (
          <div className="chip-row">
            <span className="hint">{q.field === 'schedule.match_minutes'
              ? 'Set the pitch time per match to at least the length of a match.'
              : 'More days, longer days, more pitches or more matches a day fix this.'}</span>
            <button className="btn btn--ghost btn--sm" onClick={() => setEditing(true)}>Change the schedule</button>
          </div>
        )
      ) : q.options.length > 0 ? (
        <div className="chip-row">
          {q.options.map((o) => (
            <button key={o} className="btn btn--ghost btn--sm" disabled={action.busy} onClick={() => answer(o)}>{optionLabel(q.field, o)}</button>
          ))}
        </div>
      ) : (
        <form className="setup-answer" onSubmit={(e) => { e.preventDefault(); answer(value) }}>
          <input aria-label="Your answer" value={value} onChange={(e) => setValue(e.target.value)} placeholder={QUESTION_HINT[q.field] ?? ''} />
          <button className="btn btn--accent btn--sm" disabled={!value.trim() || action.busy}>Answer</button>
        </form>
      )}
      <Notice action={action} />
    </li>
  )
}

/** The changes the backend understands for an assumption, as buttons. */
function choicesFor(a, draft) {
  if (a.field === 'rules.tiebreakers') return [a.chosen, ...a.alternatives].map((v) => ({ value: v, label: TIEBREAK_PRESETS[v] ?? v }))
  if (a.field === 'format' && draft.teams.length >= 3) {
    return [{ value: 'league', label: 'Everyone plays everyone once' }, { value: 'double_league', label: '… twice (home and away)' }]
  }
  return []
}

function Assumption({ setup, a, onChange }) {
  const action = useAction(onChange, async () => {})
  const draft = setup.draft.draft
  const choices = choicesFor(a, draft).filter((c) => c.value !== a.chosen)
  const change = (value) => action.run(() => api.changeSetupDraft(setup.id, setup.draft.version, a.field, value))
  return (
    <li className="setup-assumption">
      <span aria-hidden="true">💡</span>
      <div>
        <p><strong>{TIEBREAK_PRESETS[a.chosen] ?? a.chosen}</strong> — {a.reason}</p>
        {choices.length > 0 && (
          <div className="chip-row">
            <span className="hint">Prefer:</span>
            {choices.map((c) => <button key={c.value} className="btn btn--ghost btn--sm" disabled={action.busy} onClick={() => change(c.value)}>{c.label}</button>)}
          </div>
        )}
        <Notice action={action} />
      </div>
    </li>
  )
}

function Quote({ draft, field }) {
  const q = draft.quotes?.[field]
  return q ? <span className="setup-quote" title="From your documents">“{q}”</span> : null
}

function Summary({ setup, onEditSchedule }) {
  const d = setup.draft.draft
  const rules = d.rules
  const match = rules.match ?? {}
  const pts = rules.points?.table ?? {}
  const fmt = d.format ?? {}
  const groups = fmt.group_sizes ?? []
  const ko = fmt.knockout
  const s = d.schedule
  return (
    <div className="setup-summary">
      <section className="profile-card">
        <h3>Rules</h3>
        <dl className="setup-facts">
          <div><dt>Points</dt><dd>Win {pts.win ?? 3} · draw {pts.draw ?? 1} · loss {pts.loss ?? 0} <Quote draft={d} field="rules.points" /></dd></div>
          <div><dt>Match</dt><dd>{match.periods ?? 2} × {match.period_minutes ?? '?'} min{match.extra_time ? ', extra time' : ''}
            {ko && match.penalties_in_knockout !== false ? ', penalties in the knockout' : ''} <Quote draft={d} field="rules.match" /></dd></div>
          <div><dt>Ties broken by</dt><dd>{tiebreakers(rules.tiebreakers)} <Quote draft={d} field="rules.tiebreakers" /></dd></div>
        </dl>
      </section>
      <section className="profile-card">
        <h3>Format</h3>
        <dl className="setup-facts">
          <div><dt>Teams</dt><dd>{d.teams.length}</dd></div>
          {groups.length > 0 && (
            <div><dt>Groups</dt><dd>{groups.length > 1 ? `${groups.length} groups (${groups.join(', ')} teams)` : 'One table: everyone plays everyone'}
              {fmt.group_rounds > 1 ? `, ${fmt.group_rounds} rounds` : ''}</dd></div>
          )}
          {ko && <div><dt>Knockout</dt><dd>{groups.length > 0 ? `Top ${rules.advancement?.per_group ?? 2} of each group → ` : 'All teams, no groups: '}
            {ko.rounds.map((r) => STAGE[r] ?? r).join(' → ')}
            {ko.third_place_match ? ' (+ third place)' : ''}</dd></div>}
        </dl>
      </section>
      <section className="profile-card">
        <div className="section-head"><h3>Schedule</h3><button className="link-btn link-btn--accent" onClick={onEditSchedule}>{s ? 'Change' : 'Set days and pitches'}</button></div>
        {s ? (
          <dl className="setup-facts">
            <div><dt>Days</dt><dd>{s.days.map((day) => `${day.date} ${hhmm(day.start)}–${hhmm(day.end)}`).join(' · ')}</dd></div>
            <div><dt>Pitches</dt><dd>{s.pitches.join(', ')}</dd></div>
            <div><dt>Per match</dt><dd>{s.match_minutes} min + {s.break_minutes} min changeover · rest ≥ {s.min_rest_minutes} min · max {s.max_matches_per_team_per_day} a day</dd></div>
          </dl>
        ) : <p className="empty">Not known yet: tell us when and where it’s played.</p>}
      </section>
      <section className="profile-card">
        <h3>Teams ({d.teams.length})</h3>
        <ol className="setup-teams">
          {d.teams.map((t) => (
            <li key={t.key}>{t.name}{t.organisation ? <span className="hint"> · {t.organisation}</span> : ''}
              {t.previous_placement ? <span className="hint"> · placed {t.previous_placement} last time</span> : ''}</li>
          ))}
        </ol>
      </section>
    </div>
  )
}

export default function ReviewStep({ setup, onChange, onNext }) {
  const [editSchedule, setEditSchedule] = useState(false)
  if (!setup.draft) return <p className="empty">Upload the documents first.</p>
  const { open_questions: questions, assumptions } = setup.draft
  const locked = setup.status === 'published'
  const saved = (s) => {
    setEditSchedule(false)
    onChange(s)
  }
  return (
    <div className="wiz-card setup-review">
      {questions.length > 0 && !locked && (
        <section className="profile-card setup-questions">
          <h2>{questions.length === 1 ? 'One question' : `${questions.length} questions`} for you</h2>
          <ul>{questions.map((q) => <Question key={`${q.id}:${setup.draft.version}`} setup={setup} q={q} onChange={onChange} />)}</ul>
        </section>
      )}
      {editSchedule && !locked ? (
        <section className="profile-card"><h2>When and where</h2>
          <ScheduleForm setup={setup} onSaved={saved} onCancel={() => setEditSchedule(false)} />
        </section>
      ) : (
        <Summary setup={setup} onEditSchedule={() => setEditSchedule(true)} />
      )}
      {assumptions.length > 0 && (
        <section className="profile-card">
          <h2>What we assumed</h2>
          <p className="hint">Your documents didn’t say, so we chose common, fair practice. Change anything you disagree with.</p>
          <ul className="setup-assumptions">
            {assumptions.map((a) => <Assumption key={`${a.id}:${setup.draft.version}`} setup={setup} a={a} onChange={onChange} />)}
          </ul>
        </section>
      )}
      <div className="wiz-nav">
        <span className="hint">
          {questions.length ? 'Answer the questions to get the draw and the schedule.'
            : setup.status === 'drawing' ? 'Drawing and scheduling…' : 'All set: the engine has drawn the groups and planned the schedule.'}
        </span>
        <button className="btn btn--accent" disabled={!['ready', 'published'].includes(setup.status)} onClick={onNext}>Next: draw & schedule →</button>
      </div>
    </div>
  )
}
