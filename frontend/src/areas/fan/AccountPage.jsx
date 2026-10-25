import { useRef, useState } from 'react'
import ClubCrest from '../../components/ClubCrest'
import TeamBadge from '../../components/TeamBadge'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { api } from '../../api/client'
import { formatDate as formatDay } from '../../utils/time'

const formatDate = (ts) => formatDay(ts, { long: true })

const LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'fi', label: 'Suomi' },
  { id: 'bn', label: 'বাংলা (Bangla)' },
]


function ProfileCard({ me, replaceMe }) {
  const [form, setForm] = useState({ name: me.name, email: me.email ?? '', language: me.language })
  const [status, setStatus] = useState({ state: 'idle', message: '' })
  const dirty = form.name !== me.name || form.email !== (me.email ?? '') || form.language !== me.language

  const save = async (e) => {
    e.preventDefault()
    const patch = {}
    if (form.name.trim() !== me.name) patch.name = form.name.trim()
    if (form.email.trim() !== (me.email ?? '')) patch.email = form.email.trim()
    if (form.language !== me.language) patch.language = form.language
    setStatus({ state: 'saving', message: '' })
    try {
      replaceMe(await api.updateMe(patch))
      setStatus({ state: 'saved', message: 'Saved.' })
    } catch (err) {
      setStatus({ state: 'error', message: err.status === 422 ? 'Please check the name and email.' : err.message })
    }
  }

  return (
    <section className="account-card" aria-labelledby="profile-h">
      <h2 id="profile-h">Profile</h2>
      <form className="account-form" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input value={form.name} required maxLength={60} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={form.email} maxLength={120} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </label>
        <label className="field">
          <span>Language</span>
          <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
            {LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
          <small>Used for stories and match reports when that language is available.</small>
        </label>
        <div className="account-actions">
          {status.message && (
            <span className={status.state === 'error' ? 'form-error' : 'form-ok'} role="status">{status.message}</span>
          )}
          <button className="btn btn--accent btn--sm" disabled={!dirty || status.state === 'saving'}>Save changes</button>
        </div>
      </form>
    </section>
  )
}

function PlanCard({ me, onNavigate }) {
  const { clubs } = useCatalog()
  const p = me.premium
  const club = p && clubs[p.viaClubId]
  return (
    <section className={`account-card plan-card${p ? ' plan-card--premium' : ''}`} aria-labelledby="plan-h">
      <div className="plan-top">
        <h2 id="plan-h">Plan</h2>
        <span className={`plan-badge${p ? ' is-premium' : ''}`}>{p ? '★ Premium' : 'Free'}</span>
      </div>
      {p ? (
        <dl className="plan-facts">
          <div>
            <dt>Granted by</dt>
            <dd>
              {club ? (
                <button className="related-team" onClick={() => onNavigate({ type: 'club', clubId: club.id })}>
                  <ClubCrest club={club} size={20} /> {club.name}
                </button>
              ) : (
                p.viaClubName
              )}
            </dd>
          </div>
          <div>
            <dt>Valid until</dt>
            <dd>{p.validUntil ? formatDate(p.validUntil) : '—'}</dd>
          </div>
          <div>
            <dt>Includes</dt>
            <dd>Live scores, live timelines and “if it ends like this” stakes for every match.</dd>
          </div>
        </dl>
      ) : (
        <p className="page-sub">
          You can follow clubs and read results and stories for free. Live matches need Premium — it usually comes
          with your club membership. Ask your club for an invite code.
        </p>
      )}
    </section>
  )
}

function InviteCode({ replaceMe }) {
  const [code, setCode] = useState('')
  const [status, setStatus] = useState({ state: 'idle', message: '' })
  const redeem = async (e) => {
    e.preventDefault()
    setStatus({ state: 'saving', message: '' })
    try {
      const me = await api.redeemCode(code)
      replaceMe(me)
      setCode('')
      setStatus({ state: 'ok', message: `Premium activated — granted by ${me.premium.viaClubName}.` })
    } catch (err) {
      setStatus({ state: 'error', message: err.message })
    }
  }
  return (
    <section className="account-card" aria-labelledby="code-h">
      <h2 id="code-h">Have an invite code?</h2>
      <form className="code-form" onSubmit={redeem}>
        <label className="visually-hidden" htmlFor="invite-code">Invite code</label>
        <input
          id="invite-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="e.g. CLUB-2026"
          autoComplete="off"
          spellCheck={false}
          minLength={3}
          maxLength={40}
          required
        />
        <button className="btn btn--accent btn--sm" disabled={status.state === 'saving' || code.trim().length < 3}>Redeem</button>
      </form>
      {status.message && (
        <p className={status.state === 'error' ? 'form-error' : 'form-ok'} role="status">{status.message}</p>
      )}
    </section>
  )
}

function ClubRoles({ me, onNavigate }) {
  const { clubs } = useCatalog()
  return (
    <section className="account-card" aria-labelledby="roles-h">
      <h2 id="roles-h">Club roles</h2>
      <ul className="result-list">
        {me.roles.map((r) => (
          <li className="result-row" key={`${r.clubId}:${r.role}`}>
            <button className="rr-main" onClick={() => onNavigate({ type: 'club', clubId: r.clubId })}>
              {clubs[r.clubId] && <ClubCrest club={clubs[r.clubId]} size={30} />}
              <span className="rr-text">
                <span className="rr-title">{r.label}</span>
                <span className="rr-sub">{r.clubName}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function FamilyLinks({ me, onNavigate }) {
  return (
    <section className="account-card" aria-labelledby="family-h">
      <h2 id="family-h">Family links</h2>
      {me.family.length ? (
        <>
          <p className="page-sub">Junior players you’re linked to as a guardian. Their profiles stay private to everyone else.</p>
          <ul className="result-list">
            {me.family.map(({ player, relation }) => (
              <li className="result-row" key={player.id}>
                <button className="rr-main" onClick={() => onNavigate({ type: 'player', playerId: player.id })}>
                  <span className="player-num" style={{ '--team': player.team.color }} aria-hidden="true">{player.number}</span>
                  <span className="rr-text">
                    <span className="rr-title">{player.name}</span>
                    <span className="rr-sub">
                      <TeamBadge team={player.team} size={16} /> {player.team.name} · you are their {relation}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="page-sub">No linked junior players. When your child joins a club, the club can send you a link request.</p>
      )}
    </section>
  )
}

function DeleteAccount({ replaceMe, onNavigate }) {
  const dialog = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const confirm = async () => {
    setBusy(true)
    try {
      replaceMe(await api.deleteAccount())
      dialog.current?.close()
      onNavigate({ type: 'home' })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }
  return (
    <section className="account-card danger-zone" aria-labelledby="delete-h">
      <h2 id="delete-h">Delete account</h2>
      <p className="page-sub">Removes your profile, follows, alert settings, family links and Premium access. This can’t be undone.</p>
      <button className="btn btn--danger btn--sm" onClick={() => dialog.current?.showModal()}>Delete my account…</button>
      <dialog ref={dialog} className="modal" aria-labelledby="delete-confirm-h">
        <div className="modal-body">
          <h2 id="delete-confirm-h">Delete your account?</h2>
          <p className="page-sub">Everything listed above will be removed and you’ll be signed out.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button className="btn btn--ghost" onClick={() => dialog.current?.close()} autoFocus>Keep my account</button>
            <button className="btn btn--danger" onClick={confirm} disabled={busy}>{busy ? 'Deleting…' : 'Delete account'}</button>
          </div>
        </div>
      </dialog>
    </section>
  )
}

export default function AccountPage({ onNavigate }) {
  const { me, signIn, replaceMe, requestLogin } = useMeContext()

  if (!me?.signedIn) {
    return (
      <>
        <div className="page-head"><h1>Account</h1></div>
        <div className="premium-lock">
          <span className="lock-icon" aria-hidden="true">👤</span>
          <div>
            <h2>For members</h2>
            <p>Sign in to see your plan, redeem a club invite code and manage your account.</p>
            <div className="lock-actions">
              <button className="btn btn--accent btn--sm" onClick={() => requestLogin()}>Log in</button>
              <button className="btn btn--ghost btn--sm" onClick={() => requestLogin('signup')}>Create account</button>
              <button className="btn btn--ghost btn--sm" onClick={() => signIn('premium')}>Try the demo</button>
            </div>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <h1>Account</h1>
        <p className="page-sub">Your profile, plan and family links.</p>
      </div>
      <div className="account-grid">
        <ProfileCard me={me} replaceMe={replaceMe} />
        <PlanCard me={me} onNavigate={onNavigate} />
        <InviteCode replaceMe={replaceMe} />
        <FamilyLinks me={me} onNavigate={onNavigate} />
        {me.roles.length > 0 && <ClubRoles me={me} onNavigate={onNavigate} />}
        <DeleteAccount replaceMe={replaceMe} onNavigate={onNavigate} />
      </div>
    </>
  )
}
