import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useMeContext } from '../../app/providers/me'
import { api } from '../../api/client'
import { safeNext } from '../../app/router'

// No passwords (ADR 0008): sign-up and log-in email a magic link; opening it lands on
// /auth/verify?token=…, which signs this browser in.

const LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'fi', label: 'Suomi' },
  { id: 'bn', label: 'বাংলা (Bangla)' },
]

function browserLanguage() {
  const l = (navigator.language ?? 'en').slice(0, 2)
  return LANGUAGES.some((x) => x.id === l) ? l : 'en'
}

function useAuthDone() {
  const { authenticated } = useMeContext()
  const routerNavigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  return async (me, dest) => {
    await authenticated(me)
    routerNavigate(dest ?? next, { replace: true })
  }
}

function errorText(err, fallback) {
  if (err.code === 'validation_error') return 'Please check the email address and your name.'
  if (err.code === 'rate_limited') return 'Too many links asked for. Please wait a moment and try again.'
  return err.message || fallback
}

function LinkSent({ email }) {
  return (
    <div className="auth-form">
      <p className="form-ok" role="status">
        Check your inbox: we sent a sign-in link to <strong>{email}</strong>. It works for 15 minutes, once.
      </p>
      {import.meta.env.DEV && (
        <div className="dev-box">
          <strong>Dev mode</strong> — the email goes to Mailpit (<a href="http://localhost:8025" target="_blank" rel="noreferrer">localhost:8025</a>)
          with the real backend, or to the mock’s outbox (<a href="/mock/outbox" target="_blank" rel="noreferrer">/mock/outbox</a>).
        </div>
      )}
    </div>
  )
}

function SignupForm() {
  const { pendingFollow } = useMeContext()
  const [form, setForm] = useState({ email: '', name: '', language: browserLanguage(), acceptTerms: false, adult: false })
  const [status, setStatus] = useState({ busy: false, error: '', sent: '' })
  if (status.sent) return <LinkSent email={status.sent} />
  const submit = async (e) => {
    e.preventDefault()
    setStatus({ busy: true, error: '', sent: '' })
    try {
      await api.signup({ email: form.email.trim(), name: form.name.trim(), language: form.language, follow: pendingFollow })
      setStatus({ busy: false, error: '', sent: form.email.trim() })
    } catch (err) {
      setStatus({ busy: false, error: errorText(err, 'Couldn’t send the link.'), sent: '' })
    }
  }
  return (
    <form className="auth-form" onSubmit={submit}>
      <label className="field">
        <span>Email</span>
        <input type="email" autoComplete="email" required maxLength={254} value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </label>
      <label className="field">
        <span>Your name</span>
        <input autoComplete="name" required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </label>
      <label className="field">
        <span>Language</span>
        <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
          {LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
        </select>
      </label>
      <label className="consent">
        <input type="checkbox" required checked={form.adult} onChange={(e) => setForm({ ...form, adult: e.target.checked })} />
        <span>I am 13 or older.</span>
      </label>
      <label className="consent">
        <input type="checkbox" required checked={form.acceptTerms} onChange={(e) => setForm({ ...form, acceptTerms: e.target.checked })} />
        <span>
          I agree to the <a href="/terms" target="_blank" rel="noreferrer">Terms of use</a> and the{' '}
          <a href="/privacy" target="_blank" rel="noreferrer">Privacy policy</a>.
        </span>
      </label>
      {status.error && <p className="form-error" role="alert">{status.error}</p>}
      <button className="btn btn--accent auth-submit" disabled={status.busy || !form.acceptTerms || !form.adult}>
        {status.busy ? 'Sending…' : 'Email me a sign-up link'}
      </button>
    </form>
  )
}

function LoginForm({ next }) {
  const done = useAuthDone()
  const { signIn } = useMeContext()
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState({ busy: false, error: '', sent: '' })
  if (status.sent) return <LinkSent email={status.sent} />
  const submit = async (e) => {
    e.preventDefault()
    setStatus({ busy: true, error: '', sent: '' })
    try {
      await api.requestLink(email.trim())
      setStatus({ busy: false, error: '', sent: email.trim() })
    } catch (err) {
      setStatus({ busy: false, error: errorText(err, 'Couldn’t send the link.'), sent: '' })
    }
  }
  const demo = async (plan, dest) => {
    await signIn(plan)
    await done(await api.me(), dest)
  }
  // Demo accounts (development only): a fan with Premium, an event organiser and an editor.
  const wanted = safeNext(next)
  const pick = (area) => (wanted === area || wanted.startsWith(`${area}/`) ? wanted : area)
  return (
    <>
      <form className="auth-form" onSubmit={submit}>
        <label className="field">
          <span>Email</span>
          <input type="email" autoComplete="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        {status.error && <p className="form-error" role="alert">{status.error}</p>}
        <button className="btn btn--accent auth-submit" disabled={status.busy}>{status.busy ? 'Sending…' : 'Email me a sign-in link'}</button>
      </form>
      {import.meta.env.DEV && (
        <div className="demo-box">
          <span>Just looking around?</span>
          <button className="btn btn--ghost btn--sm" onClick={() => demo('premium')}>Try the demo fan</button>
          <button className="link-btn demo-club" onClick={() => demo('scorer', pick('/score'))}>
            Match scorer? Try the demo scorer account →
          </button>
          <button className="link-btn demo-club" onClick={() => demo('publisher', pick('/publisher'))}>
            Event organiser? Try the demo organiser account →
          </button>
          <button className="link-btn demo-club" onClick={() => demo('editor', pick('/editor'))}>
            Sports desk editor? Try the demo editor account →
          </button>
        </div>
      )}
    </>
  )
}

function Verify({ token }) {
  const done = useAuthDone()
  const [error, setError] = useState('')
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return // a link works once: never send it twice (React dev re-runs effects)
    started.current = true
    api.verify(token).then((me) => done(me)).catch((err) => setError(errorText(err, 'This link didn’t work.')))
  }, [token, done])
  return error ? (
    <div className="auth-form">
      <p className="form-error" role="alert">{error}</p>
      <p className="page-sub">Links work for 15 minutes and only once. Ask for a new one below.</p>
    </div>
  ) : (
    <p className="page-sub" aria-busy="true"><span className="spinner" /> Signing you in…</p>
  )
}

const COPY = {
  signup: { title: 'Create account', sub: 'Follow your clubs, get alerts and see what your team needs. Free.' },
  login: { title: 'Log in', sub: 'We’ll email you a link — no password needed.' },
  verify: { title: 'Signing in', sub: '' },
}

export default function AuthView({ mode, onNavigate }) {
  const { me } = useMeContext()
  const [params] = useSearchParams()
  const routerNavigate = useNavigate()
  const next = params.get('next') ?? undefined
  const token = params.get('token')
  const c = COPY[mode] ?? COPY.login

  if (me?.signedIn && mode !== 'verify') {
    return (
      <div className="auth-card">
        <h1>You’re logged in</h1>
        <p className="page-sub">Signed in as {me.email ?? me.name}.</p>
        <button className="btn btn--accent" onClick={() => routerNavigate(safeNext(next), { replace: true })}>Continue</button>
      </div>
    )
  }

  return (
    <div className="auth-card">
      <h1>{c.title}</h1>
      {c.sub && <p className="page-sub">{c.sub}</p>}
      {mode === 'signup' && <SignupForm />}
      {mode === 'login' && <LoginForm next={next} />}
      {mode === 'verify' && (token ? <Verify token={token} /> : <p className="form-error">This link is missing its token.</p>)}
      <p className="auth-switch">
        {mode === 'signup' && (
          <>Already have an account? <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'login', next })}>Log in</button></>
        )}
        {mode !== 'signup' && (
          <>New here? <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'signup', next })}>Create an account</button></>
        )}
      </p>
    </div>
  )
}
