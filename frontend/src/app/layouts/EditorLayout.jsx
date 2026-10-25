import Icon from '../../components/Icon'
import '../../styles/editor.css'
import { useMeContext } from '../providers/me'

/**
 * Editor desk shell (E1–E3): one dense top bar, the page below. Made for desktop screens;
 * on small screens a note says so and the page still works (tables scroll sideways).
 */
export default function EditorLayout({ section, onNavigate, children }) {
  const { me, signOut } = useMeContext()
  return (
    <div className="desk">
      <header className="desk-top">
        <button className="desk-brand" onClick={() => onNavigate({ type: 'editor' })}>
          <span className="brand-mark" aria-hidden="true">LP</span>
          <span>Editor desk</span>
        </button>
        <nav className="desk-nav" aria-label="Editor desk">
          {[['queue', 'Review queue', { type: 'editor' }], ['published', 'Published', { type: 'editor', section: 'published' }]].map(([id, label, v]) => (
            <button key={id} className={section === id ? 'is-active' : ''} aria-current={section === id ? 'page' : undefined}
              onClick={() => onNavigate(v)}>{label}</button>
          ))}
        </nav>
        <span className="desk-spacer" />
        <button className="desk-link" onClick={() => onNavigate({ type: 'home' })}>
          <Icon name="home" size={15} /> OurSport
        </button>
        <span className="desk-user">
          <span className="avatar avatar--sm" aria-hidden="true">{(me?.name ?? 'E').charAt(0).toUpperCase()}</span>
          {me?.name}
        </span>
        <button className="btn btn--ghost btn--sm" onClick={signOut}>Sign out</button>
      </header>
      <p className="desk-narrow" role="note">The editor desk is made for desktop screens. Use a wider window for the full table.</p>
      <main className="desk-main" tabIndex={-1}>{children}</main>
    </div>
  )
}
