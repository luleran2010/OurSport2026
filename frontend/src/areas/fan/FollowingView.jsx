import { useState } from 'react'
import ClubCrest from '../../components/ClubCrest'
import TeamBadge from '../../components/TeamBadge'
import Icon from '../../components/Icon'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { formatDateRange } from '../../utils/time'

const TOGGLES = [
  { key: 'matchStart', label: 'Match start' },
  { key: 'liveUpdates', label: 'Live updates' },
  { key: 'results', label: 'Results' },
  { key: 'scenarioChanges', label: 'Scenario changes' },
  { key: 'news', label: 'News' },
]

const SECTIONS = [
  { key: 'clubs', title: 'Clubs', empty: 'You don’t follow any clubs yet.', explore: 'clubs' },
  { key: 'teams', title: 'Teams', empty: 'You don’t follow any teams yet.', explore: 'teams' },
  { key: 'events', title: 'Events', empty: 'You don’t follow any events yet.', explore: null },
]

function Toggle({ on, label, onChange }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`switch${on ? ' is-on' : ''}`} onClick={() => onChange(!on)}>
      <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
      {label}
    </button>
  )
}

function FollowRow({ item, onOpen, onUnfollow, onNotify }) {
  const { sportIcon } = useCatalog()
  const n = item.notifications
  const alerts = TOGGLES.filter((t) => n[t.key]).length
  return (
    <li className="follow-row">
      <div className="follow-main">
        <button className="rr-main" onClick={onOpen}>
          {item.kind === 'club' ? (
            <ClubCrest club={item} size={34} />
          ) : item.kind === 'team' ? (
            <TeamBadge team={item} size={36} />
          ) : (
            <span className="event-icon"><Icon name="flag" size={20} /></span>
          )}
          <span className="rr-text">
            <span className="rr-title">{item.name}</span>
            <span className="rr-sub">
              {item.sport && `${sportIcon(item.sport)} `}
              {item.kind === 'tournament' ? `${formatDateRange(item.startsAt, item.endsAt)} · ${item.subtitle}` : item.subtitle}
            </span>
          </span>
        </button>
        <button className="btn btn--ghost btn--sm" onClick={onUnfollow} aria-label={`Unfollow ${item.name}`}>Unfollow</button>
      </div>
      <div className="follow-alerts" role="group" aria-label={`Notifications for ${item.name}`}>
        <span className="alerts-label">🔔 {alerts ? `${alerts} of ${TOGGLES.length} alerts` : 'Alerts off'}</span>
        {TOGGLES.map((t) => (
          <Toggle key={t.key} label={t.label} on={n[t.key]} onChange={(v) => onNotify(t.key, v)} />
        ))}
      </div>
    </li>
  )
}

export default function FollowingView({ follow, onNavigate }) {
  const { me, requestLogin } = useMeContext()
  const signedIn = Boolean(me?.signedIn)
  // Reload when follows change anywhere in the app (e.g. a Follow button on another page).
  const key = `${signedIn}:${JSON.stringify(me?.follows ?? {})}`
  const state = useLoad(() => (signedIn ? api.myFollows() : Promise.resolve(null)), key)
  // Optimistic local changes laid over the loaded lists: alert settings and just-unfollowed items.
  const [prefs, setPrefs] = useState({})
  const [removed, setRemoved] = useState(() => new Set())
  const [error, setError] = useState('')
  const lists = state.data
    ? Object.fromEntries(
        SECTIONS.map(({ key: k }) => [
          k,
          state.data[k]
            .filter((i) => !removed.has(i.id))
            .map((i) => (prefs[i.id] ? { ...i, notifications: prefs[i.id] } : i)),
        ]),
      )
    : null

  if (!signedIn) {
    return (
      <>
        <div className="page-head"><h1>Following</h1></div>
        <div className="premium-lock">
          <span className="lock-icon" aria-hidden="true">👤</span>
          <div>
            <h2>For members</h2>
            <p>Sign in to manage the clubs, teams and events you follow, and choose which alerts you get.</p>
            <div className="lock-actions"><button className="btn btn--accent btn--sm" onClick={() => requestLogin()}>Log in</button></div>
          </div>
        </div>
      </>
    )
  }

  const unfollow = (item) => {
    setRemoved((r) => new Set(r).add(item.id))
    if (item.kind === 'club') follow.toggleClub(item.targetId)
    else if (item.kind === 'team') follow.toggle(item.targetId)
    else follow.toggleTournament(item.targetId)
  }

  const notify = async (item, field, value) => {
    const patchLocal = (p) => setPrefs((all) => ({ ...all, [item.id]: p }))
    patchLocal({ ...item.notifications, [field]: value })
    try {
      const saved = await api.setNotifications(item.id, { [field]: value })
      patchLocal(saved.notifications)
      setError('')
    } catch {
      patchLocal(item.notifications)
      setError('Couldn’t save that notification setting. Please try again.')
    }
  }

  const open = (item) =>
    onNavigate(
      item.kind === 'club'
        ? { type: 'club', clubId: item.targetId }
        : item.kind === 'team'
          ? { type: 'team', teamId: item.targetId }
          : { type: 'event', eventId: item.targetId },
    )

  const total = lists ? lists.clubs.length + lists.teams.length + lists.events.length : 0

  return (
    <>
      <div className="page-head following-head">
        <div>
          <h1>Following</h1>
          <p className="page-sub">
            {lists ? `${total} followed · choose which alerts you get for each.` : 'Loading…'}
          </p>
        </div>
        <button className="btn btn--accent" onClick={() => onNavigate({ type: 'explore' })}>＋ Add more</button>
      </div>

      {error && <div className="notice notice--reconnect" role="alert">{error}</div>}
      {state.status === 'error' && !lists && <p className="empty">Couldn’t load what you follow right now.</p>}

      {lists &&
        SECTIONS.map((sec) => (
          <section className="section" key={sec.key} aria-labelledby={`fs-${sec.key}`}>
            <div className="section-head">
              <h2 id={`fs-${sec.key}`}>{sec.title} <span className="count-chip">{lists[sec.key].length}</span></h2>
              <button
                className="link-btn"
                onClick={() => onNavigate(sec.explore ? { type: 'explore', q: '' } : { type: 'events' })}
              >
                Add more
              </button>
            </div>
            {lists[sec.key].length ? (
              <ul className="follow-list">
                {lists[sec.key].map((item) => (
                  <FollowRow
                    key={item.id}
                    item={item}
                    onOpen={() => open(item)}
                    onUnfollow={() => unfollow(item)}
                    onNotify={(field, value) => notify(item, field, value)}
                  />
                ))}
              </ul>
            ) : (
              <p className="empty">{sec.empty}</p>
            )}
          </section>
        ))}
    </>
  )
}
