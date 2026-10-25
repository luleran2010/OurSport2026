import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useLoad } from '../../api/useLoad'
import { clockTime, dayLabel } from '../../utils/time'

const POLL_MS = 15_000
const PAGE = 25
const REASON_LABEL = {
  sensitive_topic: 'Sensitive topic', blocked_claim: 'Blocked claim', junior_mention: 'Junior mention',
  manual_news: 'Manual news', correction: 'Correction',
}
const AGES = [
  { id: '', label: 'Any age' }, { id: 'under_30', label: 'Under 30 min' },
  { id: 'over_30', label: 'Over 30 min' }, { id: 'over_120', label: 'Over 2 h' },
]
const EMPTY = { reason: '', sport: '', event: '', language: '', age: '', assigned: '' }
const SHORTCUTS = [
  ['j / ↓', 'Next row'], ['k / ↑', 'Previous row'], ['Enter', 'Open the selected item'], ['n', 'Take next'],
  ['r', 'Refresh now'], ['/', 'Go to the filters'], ['x', 'Clear filters'], ['?', 'Show or hide shortcuts'],
]

function waited(item, now) {
  return Math.max(0, Math.floor((now - item.createdAt) / 60_000))
}

function waitText(min) {
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  return min % 60 ? `${h} h ${min % 60} min` : `${h} h`
}

function typing(el) {
  return el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

function Select({ label, value, onChange, options, any, inputRef }) {
  return (
    <label className="desk-filter">
      <span>{label}</span>
      <select ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{any}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}{o.count !== undefined ? ` (${o.count})` : ''}</option>
        ))}
      </select>
    </label>
  )
}

/** E1 Review queue: everything waiting for an editor, high priority first, then the longest-waiting. */
export default function QueueView({ onNavigate }) {
  const [filters, setFilters] = useState(EMPTY)
  const [offset, setOffset] = useState(0)
  const [tick, setTick] = useState(0)
  const [sel, setSel] = useState(0)
  const [help, setHelp] = useState(false)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const firstFilter = useRef(null)
  const rows = useRef(null)

  const params = { ...filters, cursor: offset ? String(offset) : undefined, limit: PAGE }
  const key = `${JSON.stringify(params)}#${tick}`
  const state = useLoad(() => api.editorQueue(params), key)
  const q = state.data

  // Live: the queue reloads every 15 s (and when the tab comes back into view).
  useEffect(() => {
    const id = setInterval(() => document.visibilityState === 'visible' && setTick((t) => t + 1), POLL_MS)
    const onVisible = () => document.visibilityState === 'visible' && setTick((t) => t + 1)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  const count = q?.counts.all
  useEffect(() => {
    document.title = count ? `(${count}) Review queue · OurSport` : 'Review queue · OurSport'
    return () => { document.title = 'OurSport AI' }
  }, [count])

  const setFilter = (k, v) => {
    setFilters((f) => ({ ...f, [k]: v }))
    setOffset(0)
    setSel(0)
  }
  const clear = () => {
    setFilters(EMPTY)
    setOffset(0)
    setSel(0)
  }
  const open = (item) => onNavigate({ type: 'editor', itemId: item.id })

  const takeNext = async () => {
    if (busy) return
    setBusy(true)
    setNotice(null)
    try {
      const item = await api.claimReview('next')
      open(item)
    } catch (err) {
      setNotice({ tone: err.code === 'empty' ? 'info' : 'error', text: err.message || 'Couldn’t take the next item.' })
      setTick((t) => t + 1)
    } finally {
      setBusy(false)
    }
  }

  const items = q?.items ?? []
  const current = Math.min(sel, Math.max(items.length - 1, 0))

  const onKey = useEffectEvent((e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'Escape') {
      if (help) setHelp(false)
      else if (typing(document.activeElement)) document.activeElement.blur()
      return
    }
    if (typing(document.activeElement)) return
    const k = e.key
    if (k === 'j' || k === 'ArrowDown') {
      e.preventDefault()
      setSel(Math.min(current + 1, items.length - 1))
    } else if (k === 'k' || k === 'ArrowUp') {
      e.preventDefault()
      setSel(Math.max(current - 1, 0))
    } else if (k === 'Enter' && items[current] && !(document.activeElement?.tagName === 'BUTTON')) {
      e.preventDefault()
      open(items[current])
    } else if (k === 'n') {
      takeNext()
    } else if (k === 'r') {
      setTick((t) => t + 1)
    } else if (k === '/') {
      e.preventDefault()
      firstFilter.current?.focus()
    } else if (k === 'x') {
      clear()
    } else if (k === '?') {
      setHelp((h) => !h)
    }
  })
  useEffect(() => {
    const h = (e) => onKey(e)
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  // keep the selected row in view
  useEffect(() => {
    rows.current?.querySelector(`[data-row="${current}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [current])

  if (!q) {
    if (state.status === 'error') {
      return (
        <div className="desk-page">
          <p className="form-error" role="alert">{state.error?.message || 'Couldn’t load the review queue.'}</p>
          <button className="btn btn--ghost btn--sm" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )
    }
    return <div className="desk-page" aria-busy="true"><span className="spinner" /> Loading the queue…</div>
  }

  const now = q.updatedAt
  const f = q.filters
  const active = Object.values(filters).some(Boolean)
  const assignedTabs = [
    { id: '', label: 'All', n: q.counts.all }, { id: 'none', label: 'Unassigned', n: q.counts.unassigned },
    { id: 'me', label: 'Mine', n: q.counts.mine },
  ]

  return (
    <div className="desk-page">
      <div className="desk-head">
        <h1>Review queue</h1>
        <div className="desk-counts" aria-live="polite">
          <span><b>{q.counts.all}</b> waiting</span>
          <span className="desk-count--high"><b>{q.counts.high}</b> high priority</span>
          <span className="desk-count--amber"><b>{q.counts.over_30}</b> over 30 min</span>
          <span className="desk-count--red"><b>{q.counts.over_120}</b> over 2 h</span>
        </div>
        <span className="desk-spacer" />
        <span className="desk-muted desk-updated">
          {state.status === 'loading' ? 'Updating…' : `Updated ${clockTime(q.updatedAt)} · every 15 s`}
        </span>
        <button className="btn btn--ghost btn--sm" onClick={() => setHelp((h) => !h)} aria-expanded={help}>
          Shortcuts <kbd>?</kbd>
        </button>
        <button className="btn btn--accent btn--sm" onClick={takeNext} disabled={busy || q.counts.unassigned === 0}
          title="Assign the oldest high-priority item nobody has to me">
          {busy ? 'Taking…' : 'Take next'} <kbd>n</kbd>
        </button>
      </div>

      {help && (
        <div className="desk-help" role="dialog" aria-label="Keyboard shortcuts">
          <dl>
            {SHORTCUTS.map(([k, v]) => (
              <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>
            ))}
          </dl>
        </div>
      )}

      <div className="desk-filters" role="search" aria-label="Filter the queue">
        <div className="desk-tabs" role="group" aria-label="Assigned">
          {assignedTabs.map((t) => (
            <button key={t.id} className={filters.assigned === t.id ? 'is-active' : ''} aria-pressed={filters.assigned === t.id}
              onClick={() => setFilter('assigned', t.id)}>
              {t.label} <span>{t.n}</span>
            </button>
          ))}
        </div>
        <Select label="Reason" any="All reasons" value={filters.reason} onChange={(v) => setFilter('reason', v)}
          options={f.reasons} inputRef={firstFilter} />
        <Select label="Sport" any="All sports" value={filters.sport} onChange={(v) => setFilter('sport', v)} options={f.sports} />
        <Select label="Event" any="All events" value={filters.event} onChange={(v) => setFilter('event', v)} options={f.events} />
        <Select label="Language" any="All languages" value={filters.language} onChange={(v) => setFilter('language', v)}
          options={f.languages} />
        <Select label="Waiting" any="Any age" value={filters.age} onChange={(v) => setFilter('age', v)} options={AGES.slice(1)} />
        {active && <button className="link-btn link-btn--accent" onClick={clear}>Clear filters <kbd>x</kbd></button>}
      </div>

      {notice && (
        <p className={notice.tone === 'error' ? 'form-error' : 'desk-notice'} role="status">
          {notice.text}
          <button className="link-btn" onClick={() => setNotice(null)} aria-label="Dismiss">×</button>
        </p>
      )}

      <div className="desk-table-wrap">
        <table className="desk-table">
          <thead>
            <tr>
              <th scope="col">Priority</th>
              <th scope="col">Reason</th>
              <th scope="col">Headline</th>
              <th scope="col">Match / event</th>
              <th scope="col">Created</th>
              <th scope="col">Waiting</th>
              <th scope="col">Assigned</th>
            </tr>
          </thead>
          <tbody ref={rows}>
            {items.map((it, i) => {
              const min = waited(it, now)
              const m = it.match
              return (
                <tr key={it.id} data-row={i} className={`${i === current ? 'is-selected' : ''}${it.assignedToMe ? ' is-mine' : ''}`}
                  onClick={() => open(it)} aria-selected={i === current}>
                  <td>
                    <span className={`desk-prio desk-prio--${it.priority}`}>{it.priority === 'high' ? 'High' : 'Normal'}</span>
                  </td>
                  <td>
                    <span className={`desk-reason desk-reason--${it.reason}`} title={it.reasonText}>{REASON_LABEL[it.reason]}</span>
                  </td>
                  <td className="desk-headline">
                    <button className="desk-row-link" onClick={(e) => { e.stopPropagation(); open(it) }} lang={it.language}>
                      {it.headline}
                    </button>
                    <span className="desk-sub">
                      {it.source} · {it.language.toUpperCase()} · <span className="desk-why">{it.reasonText}</span>
                    </span>
                  </td>
                  <td className="desk-event">
                    {m ? <span>{m.home.name} v {m.away.name}</span> : !it.eventName && <span className="desk-muted">—</span>}
                    {it.eventName && <span className="desk-sub">{it.eventName}</span>}
                  </td>
                  <td className="desk-nowrap">
                    {clockTime(it.createdAt)}
                    <span className="desk-sub">{dayLabel(it.createdAt, now)}</span>
                  </td>
                  <td className="desk-nowrap">
                    <span className={`desk-wait${min >= 120 ? ' desk-wait--red' : min >= 30 ? ' desk-wait--amber' : ''}`}>
                      {waitText(min)}
                    </span>
                  </td>
                  <td className="desk-nowrap">
                    {it.assignedToMe ? <b className="desk-me">You</b> : it.assignedTo ?? <span className="desk-muted">Unassigned</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {items.length === 0 && (
          <div className="desk-empty">
            {active ? <>Nothing matches these filters. <button className="link-btn link-btn--accent" onClick={clear}>Clear filters</button></>
              : 'The queue is empty. Nice work.'}
          </div>
        )}
      </div>

      {q.total > PAGE && (
        <div className="desk-pager">
          <span className="desk-muted">{offset + 1}–{Math.min(offset + PAGE, q.total)} of {q.total}</span>
          <button className="btn btn--ghost btn--sm" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE)); setSel(0) }}>
            Previous
          </button>
          <button className="btn btn--ghost btn--sm" disabled={!q.nextCursor} onClick={() => { setOffset(Number(q.nextCursor)); setSel(0) }}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}
