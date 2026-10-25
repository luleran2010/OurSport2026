import { useState } from 'react'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { timeAgo } from '../../utils/time'

const KIND = {
  match_start: { icon: '▶', label: 'Match starting' },
  live_update: { icon: '⚽', label: 'Live update' },
  result: { icon: '■', label: 'Result' },
  scenario_change: { icon: '⚖', label: 'Scenario change' },
  news: { icon: '✎', label: 'New story' },
}
const DISMISS_KEY = 'oursport.pushPromptDismissed'

function readDismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

function PushPrompt() {
  const supported = typeof window !== 'undefined' && 'Notification' in window
  const [permission, setPermission] = useState(supported ? Notification.permission : 'unsupported')
  const [dismissed, setDismissed] = useState(readDismissed)

  if (!supported || dismissed) return null
  if (permission === 'granted') {
    return <p className="push-state">🔔 Device alerts are on for this browser.</p>
  }
  if (permission === 'denied') {
    return <p className="push-state">Device alerts are blocked for this site. You can allow them in your browser’s site settings.</p>
  }
  const dismiss = () => {
    setDismissed(true)
    try {
      localStorage.setItem(DISMISS_KEY, '1')
    } catch {
      /* ignore */
    }
  }
  return (
    <div className="push-prompt" role="region" aria-label="Device alerts">
      <span className="lock-icon" aria-hidden="true">🔔</span>
      <div>
        <strong>Get alerts on this device</strong>
        <span>Kick-offs, goals and results for what you follow — even when OurSport isn’t the open tab.</span>
      </div>
      <div className="lock-actions">
        <button className="btn btn--ghost btn--sm" onClick={dismiss}>Not now</button>
        <button className="btn btn--accent btn--sm" onClick={async () => setPermission(await Notification.requestPermission())}>
          Turn on
        </button>
      </div>
    </div>
  )
}

export default function NotificationsView({ onNavigate, notifications, now }) {
  const { me, requestLogin } = useMeContext()
  const signedIn = Boolean(me?.signedIn)
  const [refreshKey, setRefreshKey] = useState(0)
  const first = useLoad(() => (signedIn ? api.notifications() : Promise.resolve(null)), `${signedIn}:${refreshKey}:${notifications.unread}`)
  const [more, setMore] = useState({ items: [], cursor: undefined, loading: false })
  const [readNow, setReadNow] = useState(() => new Set())

  if (!signedIn) {
    return (
      <>
        <div className="page-head"><h1>Notifications</h1></div>
        <div className="premium-lock">
          <span className="lock-icon" aria-hidden="true">🔔</span>
          <div>
            <h2>For members</h2>
            <p>Sign in to get match starts, live updates, results, scenario changes and new stories for what you follow.</p>
            <div className="lock-actions"><button className="btn btn--accent btn--sm" onClick={() => requestLogin()}>Log in</button></div>
          </div>
        </div>
      </>
    )
  }

  const page = first.data
  const items = page ? [...page.items, ...more.items.filter((m) => !page.items.some((i) => i.id === m.id))] : []
  const cursor = more.cursor === undefined ? page?.nextCursor : more.cursor
  const isRead = (n) => n.read || readNow.has(n.id)

  const open = (n) => {
    if (!isRead(n)) {
      setReadNow((s) => new Set(s).add(n.id))
      api.markRead({ ids: [n.id] }).then(() => notifications.refresh()).catch(() => {})
    }
    const l = n.link
    if (!l) return
    onNavigate(
      l.type === 'match' ? { type: 'match', matchId: l.id }
        : l.type === 'story' ? { type: 'story', storyId: l.id }
          : l.type === 'event' ? { type: 'event', eventId: l.id, tab: 'scenarios' }
            : l.type === 'team' ? { type: 'team', teamId: l.id }
              : { type: 'club', clubId: l.id },
    )
  }

  const markAll = async () => {
    await api.markRead({ all: true })
    setReadNow(new Set())
    setMore({ items: [], cursor: undefined, loading: false })
    setRefreshKey((k) => k + 1)
    notifications.refresh()
  }

  const loadMore = async () => {
    setMore((m) => ({ ...m, loading: true }))
    const next = await api.notifications(cursor)
    setMore((m) => ({ items: [...m.items, ...next.items], cursor: next.nextCursor ?? null, loading: false }))
  }

  return (
    <>
      <div className="page-head following-head">
        <div>
          <h1>Notifications</h1>
          <p className="page-sub">
            {page ? (page.unreadCount ? `${page.unreadCount} unread` : 'All caught up') : 'Loading…'} ·{' '}
            <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'following' })}>Choose alerts</button>
          </p>
        </div>
        <button className="btn btn--ghost" onClick={markAll} disabled={!page?.unreadCount}>✓ Mark all read</button>
      </div>

      <PushPrompt />

      {first.status === 'error' && !page && <p className="empty">Couldn’t load notifications right now.</p>}
      {page && !items.length && (
        <p className="empty">Nothing yet. Follow clubs, teams or events and their news will show up here.</p>
      )}
      {items.length > 0 && (
        <ul className="notif-list">
          {items.map((n) => (
            <li key={n.id}>
              <button className={`notif notif--${n.kind}${isRead(n) ? '' : ' is-unread'}`} onClick={() => open(n)}>
                <span className="notif-icon" aria-hidden="true">{KIND[n.kind].icon}</span>
                <span className="notif-text">
                  <span className="notif-kind">{KIND[n.kind].label}</span>
                  <strong>{n.title}</strong>
                  <span className="notif-body">{n.body}</span>
                </span>
                <span className="notif-time">{timeAgo(n.at, now)}</span>
                {!isRead(n) && <span className="notif-dot" aria-label="Unread" />}
              </button>
            </li>
          ))}
        </ul>
      )}
      {cursor && (
        <div className="load-more">
          <button className="btn btn--ghost btn--sm" onClick={loadMore} disabled={more.loading}>
            {more.loading ? 'Loading…' : 'Show older'}
          </button>
        </div>
      )}
    </>
  )
}
