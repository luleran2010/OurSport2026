import { useEffect } from 'react'
import { useSearchParams } from 'react-router'
import { useMeContext } from './providers/me'
import { api } from '../api/client'

/** Full-page notice shown instead of an area the visitor can't open. */
function Gate({ title, children }) {
  return (
    <div className="area-gate">
      <div className="auth-card">
        <span className="invite-icon" aria-hidden="true">🛡</span>
        <h1>{title}</h1>
        {children}
      </div>
    </div>
  )
}

const AREA = {
  // Any member may organise: creating an event makes them its owner (backend: createOrganisation + startSetup).
  publisher: { title: 'Publisher portal', login: 'Log in to create and manage your events.',
    role: 'publisher', noun: 'a publisher', global: true, open: true },
  editor: { title: 'Editor desk', login: 'Log in with your editor account to review AI texts, club news and corrections.',
    role: 'editor', noun: 'an editor', global: true },
  scorer: { title: 'Scoring', login: 'Scan the QR code on your pitch sheet, or log in as the event’s organiser.', role: 'scorer',
    noun: 'a scorer' },
}

/**
 * Only renders its children for a signed-in user who has the requested role.
 * The server checks the same on every request; this only decides what to show.
 */
export default function RoleGuard({ role, onNavigate, children }) {
  const { me, requestLogin } = useMeContext()
  const roles = Array.isArray(role) ? role : [role]
  const area = AREA[roles[0]]
  const home = <button className="link-btn" onClick={() => onNavigate({ type: 'home' })}>← Back to OurSport</button>
  // The pitch QR code opens /score?pass=<token>: keep the pass on this device, no account needed.
  const [params, setParams] = useSearchParams()
  const scanned = roles.includes('scorer') ? params.get('pass') : null
  useEffect(() => {
    if (!scanned) return
    api.setScorerPass(scanned)
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.delete('pass')
      return next
    }, { replace: true })
  }, [scanned, setParams])

  if (roles.includes('scorer') && (scanned || api.scorerPass())) return children()
  if (!me?.signedIn) {
    return (
      <Gate title={area.title}>
        <p className="page-sub">{area.login}</p>
        <button className="btn btn--accent auth-submit" onClick={() => requestLogin()}>Log in</button>
        {home}
      </Gate>
    )
  }
  const held = (me.roles ?? []).filter((r) => roles.includes(r.role))
  const allowed = area.open || held.length > 0
  if (!allowed) {
    return (
      <Gate title="No access">
        <p className="page-sub">
          {area.global
            ? `Your account isn’t ${area.noun} yet. ${area.title === 'Editor desk' ? 'Editor' : 'Publisher'} accounts are set up by OurSport.`
            : `You’re not ${area.noun} yet. ${roles[0] === 'scorer' ? 'Ask the event organiser to assign you as a scorer.' : ''}`}
        </p>
        {home}
      </Gate>
    )
  }
  return children()
}
