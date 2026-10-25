import { useMeContext } from '../providers/me'
import { useOnline } from '../../live/useOnline'
import '../../styles/scorer.css'

/**
 * Scorer area shell: light, high-contrast theme for outdoor use, big touch targets, connection status always
 * visible. One column, built for a phone held in one hand.
 */
export default function ScorerLayout({ onNavigate, children }) {
  const { me, signOut } = useMeContext()
  const online = useOnline()
  return (
    <div className="scorer">
      <header className="sc-top">
        <button className="sc-brand" onClick={() => onNavigate({ type: 'scorer' })} aria-label="My matches">
          <span className="brand-mark" aria-hidden="true">LP</span> Scorer
        </button>
        <span className={`sc-net${online ? '' : ' is-off'}`} role="status">
          <span className="sc-dot" aria-hidden="true" />{online ? 'Online' : 'Offline'}
        </span>
        <details className="sc-menu">
          <summary aria-label="Menu">{(me?.name ?? 'S').charAt(0).toUpperCase()}</summary>
          <div className="sc-menu-body">
            <strong>{me?.name}</strong>
            <button onClick={() => onNavigate({ type: 'home' })}>Back to OurSport</button>
            <button onClick={signOut}>Sign out</button>
          </div>
        </details>
      </header>
      <main className="sc-main">{children}</main>
    </div>
  )
}
