import { useEffect, useRef, useState } from 'react'
import { api } from '../../../api/client'
import { timeAgo } from '../../../utils/time'

/**
 * Right column: previews, match reports and editor news, newest first, loading more as you scroll.
 * Members see stories about what they follow; guests see everything.
 * `version` changes when new stories may exist (e.g. a game finished) and restarts from the top.
 */
export default function NewsFeed({ member, followKey, version, now, onNavigate }) {
  const scope = member ? 'following' : 'all'
  const key = `${scope}:${followKey}:${version}`
  const [feed, setFeed] = useState({ key: null, items: [], cursor: null, loading: false, done: false, error: false })
  const sentinel = useRef(null)
  const current = feed.key === key ? feed : { key, items: [], cursor: null, loading: true, done: false, error: false }

  // first page whenever the scope / follows / version change
  useEffect(() => {
    let cancelled = false
    api
      .news(scope)
      .then((page) => !cancelled && setFeed({ key, items: page.items, cursor: page.nextCursor, loading: false, done: !page.nextCursor, error: false }))
      .catch(() => !cancelled && setFeed({ key, items: [], cursor: null, loading: false, done: true, error: true }))
    return () => {
      cancelled = true
    }
  }, [key, scope])

  // infinite scroll: load the next page when the sentinel comes into view
  useEffect(() => {
    const el = sentinel.current
    if (!el || current.done || current.loading || !current.cursor) return undefined
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return
      io.disconnect()
      setFeed((f) => ({ ...f, loading: true }))
      api
        .news(scope, current.cursor)
        .then((page) =>
          setFeed((f) => (f.key !== key ? f : {
            ...f, items: [...f.items, ...page.items], cursor: page.nextCursor, loading: false, done: !page.nextCursor,
          })),
        )
        .catch(() => setFeed((f) => ({ ...f, loading: false, error: true })))
    }, { rootMargin: '300px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [current.cursor, current.done, current.loading, key, scope])

  return (
    <aside className="activity news" aria-labelledby="news-h">
      <div className="activity-head">
        <h2 id="news-h">News</h2>
        <span className="page-sub activity-scope">{member ? 'About what you follow' : 'All clubs'}</span>
      </div>
      <div className="activity-list" aria-busy={current.loading}>
        {current.items.map((s) => (
          <button key={s.id} className="news-card" onClick={() => onNavigate({ type: 'story', storyId: s.id })}>
            <span className="story-meta">
              <span className="story-tag">{s.tag}</span>
              {s.authorType === 'ai' ? <span className="news-ai" title={s.aiLabel ?? "AI-generated from club-entered data"}>✦ AI</span> : <span>{s.author}</span>}
              <span className="news-time">{timeAgo(s.publishedAt, now)}</span>
            </span>
            <strong className="news-title">{s.title}</strong>
            <span className="story-summary">{s.summary}</span>
          </button>
        ))}
        {!current.loading && !current.items.length && !current.error && (
          <p className="empty">{member ? 'No news about what you follow yet.' : 'No news yet.'}</p>
        )}
        {current.error && <p className="empty">Couldn’t load more news right now.</p>}
        {!current.done && <div ref={sentinel} className="news-more">{current.loading ? 'Loading…' : ''}</div>}
        {current.done && current.items.length > 0 && <p className="news-end">You’re all caught up.</p>}
      </div>
    </aside>
  )
}
