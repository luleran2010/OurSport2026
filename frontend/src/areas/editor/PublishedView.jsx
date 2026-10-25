import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { api } from '../../api/client'
import { useLoad } from '../../api/useLoad'
import { clockTime, dayLabel, formatDate, timeAgo } from '../../utils/time'

const PAGE = 30
const EMPTY = { q: '', date: '', event: '', author: '', corrected: '' }
const SHORTCUTS = [['/', 'Search stories'], ['j / k', 'Next / previous story'], ['c', 'Correct the selected story'],
  ['x', 'Clear filters'], ['?', 'Shortcuts']]

function typing(el) {
  return el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

function about(m) {
  return m ? `${m.home.name}${m.score ? ` ${m.score[0]}–${m.score[1]} ` : ' v '}${m.away.name}` : null
}

/** Inline "Resolve" form under a correction row: fixed / rejected + note (required to reject; the club sees it). */
function ResolveRow({ c, onDone, onCancel }) {
  const [status, setStatus] = useState('fixed')
  const [note, setNote] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api.resolveCorrection(c.id, status, note.trim() || undefined)
      onDone(status === 'fixed' ? 'Marked fixed.' : 'Report rejected.')
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }
  return (
    <tr className="ep-inline">
      <td colSpan={7}>
        <div className="ep-inline-form">
          <div className="desk-tabs" role="radiogroup" aria-label="Resolution">
            {[['fixed', 'Fixed'], ['rejected', 'Rejected']].map(([id, label]) => (
              <button key={id} role="radio" aria-checked={status === id} className={status === id ? 'is-active' : ''} onClick={() => setStatus(id)}>
                {label}
              </button>
            ))}
          </div>
          <input autoFocus value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') onCancel() }}
            placeholder={status === 'fixed' ? 'Note for the club (optional), e.g. fixed in the match data' : 'Why is it rejected? (required — the club sees this)'} />
          <button className="btn btn--ghost btn--sm" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="btn btn--accent btn--sm" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Resolve'}</button>
          {err && <span className="form-error">{err}</span>}
        </div>
        <p className="desk-muted ep-inline-hint">Resolve closes the report without changing the story. To change the text, use “Correct”.</p>
      </td>
    </tr>
  )
}

function UnpublishRow({ s, onDone, onCancel }) {
  const [reason, setReason] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api.unpublishStory(s.id, reason.trim())
      onDone(`Unpublished: “${s.title}”.`)
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }
  return (
    <tr className="ep-inline ep-inline--danger">
      <td colSpan={6}>
        <div className="ep-inline-form">
          <b>Unpublish this story?</b>
          <input autoFocus value={reason} maxLength={600} onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') onCancel() }}
            placeholder="Reason (required, kept for the record)" />
          <button className="btn btn--ghost btn--sm" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="btn btn--danger btn--sm" onClick={save} disabled={busy}>{busy ? 'Unpublishing…' : 'Unpublish'}</button>
          {err && <span className="form-error">{err}</span>}
        </div>
        <p className="desk-muted ep-inline-hint">Fans can’t open it any more and it leaves all feeds. The text is kept here.</p>
      </td>
    </tr>
  )
}

/** E3 Published content and corrections. */
export default function PublishedView({ onNavigate }) {
  const [filters, setFilters] = useState(EMPTY)
  const [status, setStatus] = useState('published')
  const [offset, setOffset] = useState(0)
  const [corrStatus, setCorrStatus] = useState('open')
  const [kick, setKick] = useState(0)
  const [resolving, setResolving] = useState(null)
  const [unpublishing, setUnpublishing] = useState(null)
  const [sel, setSel] = useState(0)
  const location = useLocation()
  const [msg, setMsg] = useState(location.state?.flash ?? null)
  const [help, setHelp] = useState(false)
  const search = useRef(null)
  const rows = useRef(null)

  const params = { ...filters, status, cursor: offset ? String(offset) : undefined, limit: PAGE }
  const storiesState = useLoad(() => api.editorStories(params), `${JSON.stringify(params)}#${kick}`)
  const corrState = useLoad(() => api.editorCorrections(corrStatus), `${corrStatus}#${kick}`)
  const p = storiesState.data
  const cs = corrState.data

  // the search box filters as you type, a moment after the last key
  const [qDraft, setQDraft] = useState('')
  useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) => (f.q === qDraft.trim() ? f : { ...f, q: qDraft.trim() }))
      setOffset(0)
    }, 250)
    return () => clearTimeout(t)
  }, [qDraft])

  const setFilter = (k, v) => {
    setFilters((f) => ({ ...f, [k]: v }))
    setOffset(0)
    setSel(0)
  }
  const clear = () => {
    setFilters(EMPTY)
    setQDraft('')
    setOffset(0)
    setSel(0)
  }
  const done = (text) => {
    setResolving(null)
    setUnpublishing(null)
    setMsg(text)
    setKick((k) => k + 1)
  }
  const correct = (itemId) => onNavigate({ type: 'editor', itemId }, { state: { from: 'published' } })

  const items = p?.items ?? []
  const current = Math.min(sel, Math.max(items.length - 1, 0))

  const onKey = useEffectEvent((e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'Escape') {
      if (help) setHelp(false)
      else if (typing(document.activeElement)) document.activeElement.blur()
      return
    }
    if (typing(document.activeElement)) return
    if (e.key === '/') {
      e.preventDefault()
      search.current?.focus()
    } else if (e.key === 'j') setSel(Math.min(current + 1, items.length - 1))
    else if (e.key === 'k') setSel(Math.max(current - 1, 0))
    else if (e.key === 'c' && items[current]?.status === 'published') correct(items[current].correctItemId)
    else if (e.key === 'x') clear()
    else if (e.key === '?') setHelp((h) => !h)
  })
  useEffect(() => {
    const h = (e) => onKey(e)
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])
  useEffect(() => {
    rows.current?.querySelector(`[data-row="${current}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [current])

  const now = p?.updatedAt ?? cs?.updatedAt
  const active = Object.values(filters).some(Boolean)

  return (
    <div className="desk-page">
      <div className="desk-head">
        <h1>Published content</h1>
        {p && (
          <div className="desk-counts">
            <span><b>{p.counts.published}</b> published</span>
            <span><b>{p.counts.corrected}</b> corrected</span>
            <span className="desk-count--amber"><b>{p.counts.reported}</b> with open reports</span>
            <span><b>{p.counts.unpublished}</b> unpublished</span>
          </div>
        )}
        <span className="desk-spacer" />
        <button className="btn btn--ghost btn--sm" onClick={() => setHelp((h) => !h)} aria-expanded={help}>Shortcuts <kbd>?</kbd></button>
      </div>
      {help && (
        <div className="desk-help" role="dialog" aria-label="Keyboard shortcuts">
          <dl>{SHORTCUTS.map(([k, v]) => <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>)}</dl>
        </div>
      )}
      {msg && <p className="desk-notice" role="status">{msg} <button className="link-btn" onClick={() => setMsg(null)} aria-label="Dismiss">×</button></p>}

      {/* ---- corrections ---- */}
      <section className="ep-section" aria-labelledby="corr-h">
        <div className="ep-section-head">
          <h2 id="corr-h">Corrections from fans and clubs</h2>
          {cs && (
            <div className="desk-tabs" role="group" aria-label="Report status">
              {[['open', 'Open'], ['fixed', 'Fixed'], ['rejected', 'Rejected'], ['all', 'All']].map(([id, label]) => (
                <button key={id} className={corrStatus === id ? 'is-active' : ''} aria-pressed={corrStatus === id} onClick={() => setCorrStatus(id)}>
                  {label} {id !== 'all' && <span>{cs.counts[id]}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        {!cs ? <p className="desk-muted"><span className="spinner" /> Loading…</p> : cs.items.length === 0 ? (
          <div className="desk-table-wrap"><div className="desk-empty">{corrStatus === 'open' ? 'No open reports. 🎉' : 'Nothing here.'}</div></div>
        ) : (
          <div className="desk-table-wrap">
            <table className="desk-table">
              <thead>
                <tr><th>Reported issue</th><th>About</th><th>What</th><th>From</th><th>Reported</th><th>Status</th><th aria-label="Actions" /></tr>
              </thead>
              <tbody>
                {cs.items.map((c) => [
                  <tr key={c.id} className="ep-row">
                    <td className="desk-headline">
                      <span className="ep-issue">“{c.message}”</span>
                      {c.correctValue && <span className="desk-sub">Correct value: <b>{c.correctValue}</b></span>}
                    </td>
                    <td>
                      {c.storyTitle ? <span>{c.storyTitle}{c.storyStatus === 'unpublished' && <span className="ep-chip ep-chip--off">Unpublished</span>}</span> : null}
                      <span className={c.storyTitle ? 'desk-sub' : ''}>{about(c.match) ?? (c.storyTitle ? '' : '—')}</span>
                    </td>
                    <td className="desk-nowrap">{c.fieldLabel}</td>
                    <td>{c.source === 'fan' ? 'Fan (anonymous)' : c.reporter}</td>
                    <td className="desk-nowrap">{timeAgo(c.createdAt, now)}<span className="desk-sub">{dayLabel(c.createdAt, now)} {clockTime(c.createdAt)}</span></td>
                    <td>
                      {c.status === 'open'
                        ? (c.assignedTo ? <span className="desk-muted">Open · {c.assignedTo}</span> : <span className="ep-chip ep-chip--warn">Open</span>)
                        : <span className={`ep-chip ep-chip--${c.status}`}>{c.status === 'fixed' ? 'Fixed' : 'Rejected'}</span>}
                      {c.resolution && <span className="desk-sub">{c.resolution}</span>}
                    </td>
                    <td className="ep-actions">
                      {c.status === 'open' && (
                        <>
                          {c.storyId && c.storyStatus === 'published' && <button className="btn btn--accent btn--sm" onClick={() => correct(c.itemId)}>Correct</button>}
                          <button className="btn btn--ghost btn--sm" onClick={() => setResolving(resolving === c.id ? null : c.id)} aria-expanded={resolving === c.id}>Resolve</button>
                        </>
                      )}
                    </td>
                  </tr>,
                  resolving === c.id && <ResolveRow key={`${c.id}-r`} c={c} onDone={done} onCancel={() => setResolving(null)} />,
                ])}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- stories ---- */}
      <section className="ep-section" aria-labelledby="stories-h">
        <div className="ep-section-head">
          <h2 id="stories-h">Stories</h2>
          <div className="desk-tabs" role="group" aria-label="Story status">
            {[['published', 'Published'], ['unpublished', 'Unpublished']].map(([id, label]) => (
              <button key={id} className={status === id ? 'is-active' : ''} aria-pressed={status === id} onClick={() => { setStatus(id); setOffset(0); setSel(0) }}>
                {label} {p && <span>{p.counts[id]}</span>}
              </button>
            ))}
          </div>
        </div>
        <div className="desk-filters" role="search" aria-label="Filter stories">
          <label className="desk-filter desk-filter--grow">
            <span>Search</span>
            <input ref={search} type="search" value={qDraft} placeholder="Headline or summary  ( / )" onChange={(e) => setQDraft(e.target.value)} />
          </label>
          <label className="desk-filter"><span>Date</span>
            <select value={filters.date} onChange={(e) => setFilter('date', e.target.value)}>
              <option value="">Any time</option><option value="24h">Last 24 h</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option>
            </select>
          </label>
          <label className="desk-filter"><span>Event</span>
            <select value={filters.event} onChange={(e) => setFilter('event', e.target.value)}>
              <option value="">All events</option>
              {(p?.events ?? []).map((ev) => <option key={ev.id} value={ev.id}>{ev.label} ({ev.count})</option>)}
            </select>
          </label>
          <label className="desk-filter"><span>Written by</span>
            <select value={filters.author} onChange={(e) => setFilter('author', e.target.value)}>
              <option value="">AI and manual</option><option value="ai">AI</option><option value="manual">Manual (club / editor)</option>
            </select>
          </label>
          <label className="desk-filter"><span>Corrected</span>
            <select value={filters.corrected} onChange={(e) => setFilter('corrected', e.target.value)}>
              <option value="">Any</option><option value="yes">Corrected</option><option value="no">Not corrected</option><option value="reported">Has an open report</option>
            </select>
          </label>
          {(active || qDraft) && <button className="link-btn link-btn--accent" onClick={clear}>Clear filters <kbd>x</kbd></button>}
        </div>

        {!p ? <p className="desk-muted"><span className="spinner" /> Loading…</p> : (
          <div className="desk-table-wrap">
            <table className="desk-table">
              <thead>
                <tr><th>Headline</th><th>Event / match</th><th>Written by</th><th>Published</th><th>Status</th><th aria-label="Actions" /></tr>
              </thead>
              <tbody ref={rows}>
                {items.map((s, i) => [
                  <tr key={s.id} data-row={i} className={`ep-row${i === current ? ' is-selected' : ''}`} onClick={() => setSel(i)}>
                    <td className="desk-headline">
                      <span className="desk-row-link" lang={s.language}>{s.title}</span>
                      <span className="desk-sub">{s.tag} · {s.language.toUpperCase()}{s.clubName ? ` · ${s.clubName}` : ''}</span>
                    </td>
                    <td className="desk-event">
                      {s.match && <span>{about(s.match)}</span>}
                      {s.eventName && <span className="desk-sub">{s.eventName}</span>}
                      {!s.match && !s.eventName && <span className="desk-muted">—</span>}
                    </td>
                    <td className="desk-nowrap">
                      {s.authorType === 'ai' ? <span className="ep-chip ep-chip--ai">✦ AI</span> : <span className="ep-chip">Manual</span>}
                      <span className="desk-sub">{s.author}</span>
                    </td>
                    <td className="desk-nowrap">{formatDate(s.publishedAt)}<span className="desk-sub">{clockTime(s.publishedAt)}</span></td>
                    <td>
                      {s.status === 'unpublished' ? (
                        <>
                          <span className="ep-chip ep-chip--off">Unpublished</span>
                          <span className="desk-sub">{formatDate(s.unpublishedAt)} by {s.unpublishedBy}: {s.unpublishReason}</span>
                        </>
                      ) : (
                        <>
                          {s.correctedAt && <span className="ep-chip ep-chip--fixed" title={s.correctionNote ?? ''}>Corrected {formatDate(s.correctedAt)}</span>}
                          {s.openCorrections > 0 && <span className="ep-chip ep-chip--warn">{s.openCorrections} open report{s.openCorrections > 1 ? 's' : ''}</span>}
                          {!s.correctedAt && !s.openCorrections && <span className="desk-muted">Live</span>}
                        </>
                      )}
                    </td>
                    <td className="ep-actions">
                      {s.status === 'published' && (
                        <>
                          <a className="btn btn--ghost btn--sm" href={`/stories/${encodeURIComponent(s.id)}`} target="_blank" rel="noreferrer">View ↗</a>
                          <button className="btn btn--ghost btn--sm" onClick={() => correct(s.correctItemId)}>Correct</button>
                          <button className="btn btn--ghost btn--sm ep-danger" onClick={() => setUnpublishing(unpublishing === s.id ? null : s.id)}
                            aria-expanded={unpublishing === s.id}>Unpublish</button>
                        </>
                      )}
                    </td>
                  </tr>,
                  unpublishing === s.id && <UnpublishRow key={`${s.id}-u`} s={s} onDone={done} onCancel={() => setUnpublishing(null)} />,
                ])}
              </tbody>
            </table>
            {items.length === 0 && <div className="desk-empty">No stories match these filters.</div>}
          </div>
        )}
        {p && p.total > PAGE && (
          <div className="desk-pager">
            <span className="desk-muted">{offset + 1}–{Math.min(offset + PAGE, p.total)} of {p.total}</span>
            <button className="btn btn--ghost btn--sm" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE)); setSel(0) }}>Previous</button>
            <button className="btn btn--ghost btn--sm" disabled={!p.nextCursor} onClick={() => { setOffset(Number(p.nextCursor)); setSel(0) }}>Next</button>
          </div>
        )}
      </section>
    </div>
  )
}
