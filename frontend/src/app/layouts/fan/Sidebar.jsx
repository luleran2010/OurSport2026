import TeamBadge from '../../../components/TeamBadge'
import ClubCrest from '../../../components/ClubCrest'
import { useMeContext } from '../../providers/me'
import Icon from '../../../components/Icon'
import { useCatalog } from '../../providers/catalog'

const MAIN = [
  { type: 'home', label: 'Home feed', icon: 'home' },
  { type: 'explore', label: 'Explore', icon: 'search' },
  { type: 'events', label: 'Events', icon: 'flag' },
  { type: 'live', label: 'Live now', icon: 'live' },
  { type: 'schedule', label: 'Schedule', icon: 'schedule' },
  { type: 'results', label: 'Results', icon: 'results' },
]

const ACCOUNT = [
  { type: 'notifications', label: 'Notifications', icon: 'bell' },
  { type: 'following', label: 'Following & alerts', icon: 'star' },
  { type: 'account', label: 'Account & plan', icon: 'profile' },
  { type: 'settings', label: 'Settings', icon: 'settings' },
]

export default function Sidebar({ view, onNavigate, followed, followedClubs = [], followedEvents = [], matches, unread = 0 }) {
  const { teams, clubs, tournaments } = useCatalog()
  const { me, signOut, requestLogin } = useMeContext()
  const live = matches.filter((m) => m.status === 'live')
  const liveTeams = new Set(live.flatMap((m) => [m.home.id, m.away.id]))

  const navItem = (it, extra = null) => {
    const active = view.type === it.type || (it.type === 'events' && view.type === 'event')
    return (
      <button
        key={it.type}
        className={`nav-item${active ? ' is-active' : ''}`}
        aria-current={active ? 'page' : undefined}
        onClick={() => onNavigate({ type: it.type })}
      >
        <span className="nav-icon"><Icon name={it.icon} /></span>
        <span className="nav-label">{it.label}</span>
        {extra}
      </button>
    )
  }

  return (
    <aside className="sidebar" aria-label="Main menu">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">LP</span>
        <span className="brand-name">OurSport<span className="brand-ai"> AI</span></span>
      </div>

      <nav className="nav-group" aria-label="Browse">
        {MAIN.map((it) =>
          navItem(it, it.type === 'live' && live.length > 0 ? <span className="nav-count">{live.length}</span> : null),
        )}
      </nav>

      {me?.signedIn && (
      <div className="nav-group">
        <div className="nav-heading">
          <span>Following</span>
          <button
            className={`link-btn${view.type === 'following' ? ' is-active' : ''}`}
            onClick={() => onNavigate({ type: 'following' })}
          >
            Manage
          </button>
        </div>
        {followed.length === 0 && followedClubs.length === 0 && followedEvents.length === 0 && (
          <p className="nav-empty">You’re not following anything yet.</p>
        )}
        {followedEvents.map((id) => {
          const t = tournaments[id]
          if (!t) return null
          const active = view.type === 'event' && view.eventId === id
          return (
            <button
              key={`event-${id}`}
              className={`nav-item team-item${active ? ' is-active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => onNavigate({ type: 'event', eventId: id })}
            >
              <span className="nav-icon"><Icon name="flag" /></span>
              <span className="nav-label">{t.name}</span>
              <span className="nav-tag">Event</span>
              {matches.some((m) => m.tournamentId === id && m.status === 'live') && <span className="live-dot" title="Games live" />}
            </button>
          )
        })}
        {followedClubs.map((id) => {
          const c = clubs[id]
          if (!c) return null
          const active = view.type === 'club' && view.clubId === id
          return (
            <button
              key={`club-${id}`}
              className={`nav-item team-item${active ? ' is-active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => onNavigate({ type: 'club', clubId: id })}
            >
              <span className="nav-crest"><ClubCrest club={c} size={22} /></span>
              <span className="nav-label">{c.name}</span>
              <span className="nav-tag">Club</span>
              {c.teamIds.some((t) => liveTeams.has(t)) && <span className="live-dot" title="Playing now" />}
            </button>
          )
        })}
        {followed.map((id) => {
          const t = teams[id]
          if (!t) return null
          const active = view.type === 'team' && view.teamId === id
          return (
            <button
              key={id}
              className={`nav-item team-item${active ? ' is-active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => onNavigate({ type: 'team', teamId: id })}
            >
              <TeamBadge team={t} size={24} />
              <span className="nav-label">{t.name}</span>
              {liveTeams.has(id) && <span className="live-dot" title="Playing now" />}
            </button>
          )
        })}
        <button className="nav-item add-team" onClick={() => onNavigate({ type: 'explore' })}>
          <span className="nav-icon"><Icon name="plus" /></span>
          <span className="nav-label">Find clubs &amp; teams</span>
        </button>
      </div>
      )}

      {me?.signedIn && (
        <nav className="nav-group" aria-label="Account">
          <div className="nav-heading"><span>Account</span></div>
          {me.roles?.some((r) => r.role === 'publisher') && (
            <button className="nav-item" onClick={() => onNavigate({ type: 'publisher' })}>
              <span className="nav-icon"><Icon name="news" /></span>
              <span className="nav-label">Publisher portal</span>
            </button>
          )}
          {me.roles?.some((r) => r.role === 'editor') && (
            <button className="nav-item" onClick={() => onNavigate({ type: 'editor' })}>
              <span className="nav-icon"><Icon name="fix" /></span>
              <span className="nav-label">Editor desk</span>
            </button>
          )}
          {me.roles?.some((r) => r.role === 'scorer') && (
            <button className="nav-item" onClick={() => onNavigate({ type: 'scorer' })}>
              <span className="nav-icon"><Icon name="whistle" /></span>
              <span className="nav-label">Score matches</span>
            </button>
          )}
          {ACCOUNT.map((it) =>
            navItem(it, it.type === 'notifications' && unread > 0 ? <span className="nav-count nav-count--soft">{unread}</span> : null),
          )}
        </nav>
      )}

      <div className="user-card">
        <span className="avatar" aria-hidden="true">{(me?.name ?? 'G').trim().charAt(0).toUpperCase() || 'G'}</span>
        <div className="user-text">
          <div className="user-name">{me?.name ?? 'Guest fan'}</div>
          <div className="user-sub">
            {me?.signedIn ? (me.premium ? `★ Premium via ${me.premium.viaClubName}` : 'Signed in') : 'Not signed in'}
          </div>
        </div>
        {me?.signedIn ? (
          <button className="btn btn--ghost btn--sm" onClick={signOut}>Sign out</button>
        ) : (
          <button className="btn btn--ghost btn--sm" onClick={() => requestLogin()}>Log in</button>
        )}
      </div>
    </aside>
  )
}
