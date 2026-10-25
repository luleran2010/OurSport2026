import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { useLoad } from '../../../api/useLoad'
import { clockTime, formatDate } from '../../../utils/time'
import PostEditor from './PostEditor'

const STATUS = {
  draft: ['Draft', 'off'], scheduled: ['Scheduled', 'info'], in_review: ['In review', 'warn'], published: ['Published', 'ok'],
  blocked: ['Blocked', 'bad'], unpublished: ['Unpublished', 'bad'],
}
const LANG = { fi: 'FI', en: 'EN', bn: 'BN' }

/** P5 News and content: every story about the event with its status, and the Write news editor. */
export default function EventContentView({ eventId, onNavigate }) {
  const [status, setStatus] = useState('')
  const [author, setAuthor] = useState('')
  const [language, setLanguage] = useState('')
  const [qDraft, setQDraft] = useState('')
  const [q, setQ] = useState('')
  const [kick, setKick] = useState(0)
  const [editor, setEditor] = useState(null) // null | 'new' | post
  const [msg, setMsg] = useState(null)
  const params = { status, author, language, q }
  const state = useLoad(() => api.eventStories(eventId, params), `${eventId}${JSON.stringify(params)}#${kick}`)
  const d = state.data

  useEffect(() => {
    const t = setTimeout(() => setQ(qDraft.trim()), 250)
    return () => clearTimeout(t)
  }, [qDraft])

  const saved = (post) => {
    setEditor(null)
    setMsg({
      draft: 'Draft saved.', published: 'Published. Fans see it now.', scheduled: `Scheduled for ${formatDate(post.publishAt)} ${clockTime(post.publishAt)}.`,
      in_review: 'Sent to the OurSport editors. It appears when they approve it.',
    }[post.status] ?? 'Saved.')
    setKick((k) => k + 1)
    window.scrollTo({ top: 0 })
  }

  if (!d) {
    if (state.status === 'error') {
      return (
        <div className="placeholder portal-placeholder">
          <p>{state.error?.message}</p>
          <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'publisher', section: 'events', sub: eventId })}>← Event</button>
        </div>
      )
    }
    return <p className="page-sub" aria-busy="true"><span className="spinner" /> Loading…</p>
  }

  const total = Object.values(d.counts).reduce((a, b) => a + b, 0)
  return (
    <div className="ev">
      <div className="page-head page-head--row">
        <div>
          <button className="link-btn" onClick={() => onNavigate({ type: 'publisher', section: 'events', sub: eventId })}>← {d.eventName}</button>
          <h1>News and content</h1>
          <p className="page-sub">AI previews and reports, and your own posts. {d.canPublish ? 'Your posts publish directly.' : 'Your posts go to the OurSport editors first.'}</p>
        </div>
        {!editor && <button className="btn btn--accent" onClick={() => { setEditor('new'); setMsg(null) }}>✎ Write news</button>}
      </div>
      {msg && <p className="ev-ok" role="status">{msg}</p>}
      {editor && <PostEditor data={d} post={editor === 'new' ? null : editor} onClose={() => setEditor(null)} onSaved={saved} />}

      <div className="ev-toolbar">
        <div className="chips chips--wrap" role="group" aria-label="Status">
          <button className={`chip chip--sm${!status ? ' is-active' : ''}`} aria-pressed={!status} onClick={() => setStatus('')}>All <span className="chip-count">{total}</span></button>
          {Object.entries(STATUS).map(([id, [label]]) => (
            <button key={id} className={`chip chip--sm${status === id ? ' is-active' : ''}`} aria-pressed={status === id} onClick={() => setStatus(status === id ? '' : id)}>
              {label} <span className="chip-count">{d.counts[id]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="ev-filters">
        <input type="search" value={qDraft} onChange={(e) => setQDraft(e.target.value)} placeholder="Search headlines" aria-label="Search headlines" />
        <select value={author} onChange={(e) => setAuthor(e.target.value)} aria-label="Written by">
          <option value="">AI and manual</option><option value="ai">AI</option><option value="manual">Manual</option>
        </select>
        <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language">
          <option value="">All languages</option>
          {['fi', 'en', 'bn'].map((l) => <option key={l} value={l}>{{ fi: 'Finnish', en: 'English', bn: 'Bangla' }[l]}</option>)}
        </select>
      </div>

      {d.items.length === 0 ? <p className="placeholder">No stories here.</p> : (
        <ul className="ct-list">
          {d.items.map((s) => {
            const [label, tone] = STATUS[s.status]
            return (
              <li key={`${s.id}-${s.status}`} className={`ct-item ct-item--${s.status}`}>
                <div className="ct-main">
                  <div className="ct-meta">
                    <span className={`ev-pill ev-pill--${tone}`}>{label}</span>
                    <span className={`ct-author${s.authorType === 'ai' ? ' ct-author--ai' : ''}`}>{s.authorType === 'ai' ? '✦ AI' : s.author}</span>
                    <span>{s.tag}</span><span>{LANG[s.language] ?? s.language}</span>
                    <span>
                      {s.status === 'scheduled' ? `Goes out ${formatDate(s.publishAt)} ${clockTime(s.publishAt)}`
                        : s.status === 'draft' ? `Saved ${formatDate(s.at)} ${clockTime(s.at)}`
                          : s.status === 'in_review' ? `Sent ${formatDate(s.at)} ${clockTime(s.at)}${s.publishAt ? ` · for ${formatDate(s.publishAt)} ${clockTime(s.publishAt)}` : ''}`
                            : `${formatDate(s.at)} ${clockTime(s.at)}`}
                    </span>
                    {s.correctedAt && <span className="ct-corrected">Corrected {formatDate(s.correctedAt)}</span>}
                  </div>
                  <h3 lang={s.language}>{s.title}</h3>
                  <p className="page-sub" lang={s.language}>{s.summary}</p>
                  {s.note && (s.status === 'blocked' || s.status === 'unpublished') && <p className="ct-note">Reason — {s.note}</p>}
                  {s.status === 'in_review' && s.authorType === 'ai' && <p className="ct-note ct-note--soft">{s.note}</p>}
                </div>
                <div className="ct-actions">
                  {s.editable && <button className="btn btn--ghost btn--sm" onClick={() => { setEditor(s); setMsg(null); window.scrollTo({ top: 0 }) }}>Edit</button>}
                  {s.status === 'published' && <a className="btn btn--ghost btn--sm" href={`/stories/${encodeURIComponent(s.id)}`} target="_blank" rel="noreferrer">View ↗</a>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
