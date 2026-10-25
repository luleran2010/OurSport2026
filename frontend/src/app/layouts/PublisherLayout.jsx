import { useRef } from 'react'
import Icon from '../../components/Icon'
import { useMeContext } from '../providers/me'
import { PUBLISHER_SECTIONS } from '../../areas/publisher/sections'

/** Publisher portal shell: left sidebar on desktop (Dashboard, Events, News), tab bar on phones. */
export default function PublisherLayout({ section, onNavigate, children }) {
  const { me, signOut } = useMeContext()
  const main = useRef(null)
  const current = PUBLISHER_SECTIONS.find((s) => s.id === section)?.id ?? (section === 'review' ? 'dashboard' : 'dashboard')
  const go = (id) => {
    onNavigate({ type: 'publisher', section: id })
    main.current?.focus()
  }
  return (
    <div className="portal portal--publisher">
      <aside className="portal-side" aria-label="Publisher portal">
        <div className="portal-brand">
          <span className="brand-mark" aria-hidden="true">LP</span>
          <span className="portal-brand-text">Publisher</span>
        </div>
        <nav className="nav-group" aria-label="Publisher sections">
          {PUBLISHER_SECTIONS.map((s) => (
            <button key={s.id} className={`nav-item${s.id === current ? ' is-active' : ''}`} aria-current={s.id === current ? 'page' : undefined}
              onClick={() => go(s.id)}>
              <span className="nav-icon"><Icon name={s.icon} /></span>
              <span className="nav-label">{s.label}</span>
            </button>
          ))}
        </nav>
        <button className="nav-item portal-back" onClick={() => onNavigate({ type: 'home' })}>
          <span className="nav-icon"><Icon name="home" /></span>
          <span className="nav-label">Back to OurSport</span>
        </button>
        <div className="user-card">
          <span className="avatar" aria-hidden="true">{(me?.name ?? 'P').charAt(0).toUpperCase()}</span>
          <div className="user-text">
            <div className="user-name">{me?.name}</div>
            <div className="user-sub">Publisher</div>
          </div>
          <button className="btn btn--ghost btn--sm" onClick={signOut}>Sign out</button>
        </div>
      </aside>

      <header className="portal-top">
        <button className="icon-btn" aria-label="Back to OurSport" onClick={() => onNavigate({ type: 'home' })}>
          <Icon name="back" size={18} />
        </button>
        <span className="portal-brand-text">Publisher</span>
      </header>

      <main className="portal-main" ref={main} tabIndex={-1}>{children}</main>

      <nav className="portal-tabs portal-tabs--3" aria-label="Publisher sections">
        {PUBLISHER_SECTIONS.map((s) => (
          <button key={s.id} className={s.id === current ? 'is-active' : ''} aria-current={s.id === current ? 'page' : undefined} onClick={() => go(s.id)}>
            <Icon name={s.icon} size={20} />
            <span>{s.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}
