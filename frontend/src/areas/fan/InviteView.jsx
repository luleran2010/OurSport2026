import { useState } from 'react'
import ClubCrest from '../../components/ClubCrest'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { formatDate as formatDay } from '../../utils/time'

const formatDate = (ts) => formatDay(ts, { long: true })


function ContactClub({ club }) {
  return (
    <p className="page-sub invite-contact">
      Please ask {club.name} for a new invite:{' '}
      {club.contactEmail ? <a href={`mailto:${club.contactEmail}?subject=OurSport%20invite`}>{club.contactEmail}</a> : 'contact the club'}.
    </p>
  )
}

export default function InviteView({ token, onNavigate }) {
  const { me, requestLogin, replaceMe } = useMeContext()
  const signedIn = Boolean(me?.signedIn)
  const state = useLoad(() => api.invite(token), `${token}:${signedIn}`)
  const [accept, setAccept] = useState({ busy: false, error: '', result: null })

  if (state.status === 'error' && !state.data) {
    return (
      <div className="auth-card invite">
        <span className="invite-icon" aria-hidden="true">✉</span>
        <h1>Invite not found</h1>
        <p className="page-sub">This invite link isn’t valid. Check that you copied the whole link, or ask the club to send it again.</p>
        <button className="btn btn--ghost" onClick={() => onNavigate({ type: 'explore' })}>Find your club</button>
      </div>
    )
  }
  if (!state.data) return <p className="page-sub">Loading invite…</p>

  const invite = accept.result?.invite ?? state.data
  const { club, offer } = invite
  const premium = offer.kind === 'premium_seat'

  const doAccept = async () => {
    setAccept({ busy: true, error: '', result: null })
    try {
      const result = await api.acceptInvite(token)
      replaceMe(result.me)
      setAccept({ busy: false, error: '', result })
    } catch (err) {
      setAccept({ busy: false, error: err.message, result: null })
    }
  }

  const header = (
    <>
      <div className="invite-club">
        <ClubCrest club={club} size={56} />
        <div>
          <span className="page-sub">{club.city}</span>
          <strong>{club.name}</strong>
        </div>
      </div>
      <span className={`invite-offer${premium ? ' is-premium' : ''}`}>{premium ? '★ Premium seat' : `Role: ${offer.label}`}</span>
    </>
  )

  if (invite.status === 'accepted_by_you') {
    return (
      <div className="auth-card invite">
        {header}
        <h1>{accept.result ? 'You’re in!' : 'Already accepted'}</h1>
        <p className="page-sub">
          {premium
            ? `Premium is active, granted by ${club.name}${me?.premium?.validUntil ? ` until ${formatDate(me.premium.validUntil)}` : ''}.`
            : `You’re now ${offer.label.toLowerCase()} for ${club.name}.`}{' '}
          You also follow {club.name} now.
        </p>
        <div className="lock-actions">
          <button className="btn btn--accent" onClick={() => onNavigate({ type: 'club', clubId: club.id })}>Go to {club.name}</button>
          {premium && <button className="btn btn--ghost" onClick={() => onNavigate({ type: 'live' })}>Watch live games</button>}
        </div>
      </div>
    )
  }

  if (invite.status === 'expired' || invite.status === 'used') {
    return (
      <div className="auth-card invite">
        {header}
        <h1>{invite.status === 'expired' ? 'This invite has expired' : 'This invite was already used'}</h1>
        <p className="page-sub">
          {invite.status === 'expired'
            ? `It was valid until ${formatDate(invite.expiresAt)}.`
            : 'Each invite link can be used once.'}
        </p>
        <ContactClub club={club} />
        <button className="btn btn--ghost" onClick={() => onNavigate({ type: 'club', clubId: club.id })}>Visit the club page</button>
      </div>
    )
  }

  return (
    <div className="auth-card invite">
      {header}
      <h1>{club.name} invites you</h1>
      <p className="invite-desc">{offer.description}</p>
      {invite.message && (
        <blockquote className="invite-message">
          “{invite.message}”
          <footer>— {invite.invitedBy}</footer>
        </blockquote>
      )}
      <p className="page-sub">Valid until {formatDate(invite.expiresAt)}.</p>

      {signedIn ? (
        <>
          <p className="page-sub">Accepting as <strong>{me.email ?? me.name}</strong>.</p>
          {accept.error && <p className="form-error" role="alert">{accept.error}</p>}
          <button className="btn btn--accent auth-submit" onClick={doAccept} disabled={accept.busy}>
            {accept.busy ? 'Accepting…' : 'Accept invite'}
          </button>
        </>
      ) : (
        <>
          <p className="page-sub">Create a free account or log in to accept — you’ll come straight back here.</p>
          <div className="invite-auth">
            <button className="btn btn--accent" onClick={() => requestLogin('signup')}>Create account</button>
            <button className="btn btn--ghost" onClick={() => requestLogin('login')}>Log in</button>
          </div>
        </>
      )}
    </div>
  )
}
