import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { Notice } from './shared'
import { useAction } from './setup'

// Step 5: choose the filming policy and publish. Nothing is public before this (golden rule 2):
// publishing creates the groups, teams, matches and rules in one go and the pages go live.

const FILMING = [
  { id: 'notice', label: 'Filming with a notice', text: 'Signs at the venue say matches may be filmed; anyone can opt out.', junior: false },
  { id: 'allowed', label: 'Filming allowed', text: 'Matches may be streamed and filmed.', junior: false },
  { id: 'consent_required', label: 'Only with consent', text: 'Players are filmed only with consent (a guardian’s for under-15s).', junior: true },
  { id: 'not_allowed', label: 'No filming', text: 'No streams or video of this event.', junior: true },
]

/** The pass link on this site: the backend builds it from WEB_BASE_URL, which may name another host. */
function onThisSite(url) {
  try {
    const u = new URL(url)
    return `${window.location.origin}${u.pathname}${u.search}`
  } catch {
    return url
  }
}

function ScorerPasses({ tournamentId }) {
  const [passes, setPasses] = useState(null)
  useEffect(() => {
    api.scorerPasses(tournamentId).then(setPasses).catch(() => setPasses([]))
  }, [tournamentId])
  if (!passes) return <p className="page-sub" aria-busy="true"><span className="spinner" /> Loading scorer passes…</p>
  if (!passes.length) return <p className="empty">No scorer passes yet.</p>
  return (
    <ul className="setup-passes">
      {passes.filter((p) => !p.revoked).map((p) => (
        <li key={p.id}>
          <strong>{p.label}</strong>
          <span className="hint"> · works {new Date(p.valid_from).toLocaleDateString()} – {new Date(Date.parse(p.valid_until) - 1).toLocaleDateString()} (the tournament days)</span>
          <div className="setup-pass-url">
            <a href={onThisSite(p.scan_url)} target="_blank" rel="noreferrer"><code>{onThisSite(p.scan_url)}</code></a>
          </div>
        </li>
      ))}
    </ul>
  )
}

function Published({ setup, onNavigate }) {
  const d = setup.draft?.draft
  const matches = setup.schedule?.matches.length ?? 0
  return (
    <div className="wiz-card">
      <section className="profile-card setup-published">
        <h2>🎉 {setup.tournament.name} is live</h2>
        <p>{d?.teams.length ?? 0} teams · {setup.draw?.groups.length ?? 0} group(s) · {matches} matches. Fans can follow it now.</p>
        <div className="chip-row">
          <button className="btn btn--accent" onClick={() => onNavigate({ type: 'event', eventId: setup.tournament_id })}>Open the fan page</button>
          <button className="btn btn--ghost" onClick={() => onNavigate({ type: 'scorer' })}>Score matches</button>
        </div>
      </section>
      <section className="profile-card">
        <h2>Scorer passes</h2>
        <p className="hint">Print one per pitch or send the link: scorers open it on their phone and score that pitch’s matches — no account needed. Keep the links private.</p>
        <ScorerPasses tournamentId={setup.tournament_id} />
      </section>
    </div>
  )
}

export default function PublishStep({ setup, reload, onBack, onNavigate }) {
  const junior = setup.tournament.is_junior
  const options = FILMING.filter((o) => !junior || o.junior)
  const [policy, setPolicy] = useState(options[0].id)
  const action = useAction(() => {}, reload)

  if (setup.status === 'published') return <Published setup={setup} onNavigate={onNavigate} />

  const questions = setup.draft?.open_questions.length ?? 0
  const checks = [
    { ok: (setup.draft?.draft.teams.length ?? 0) >= 2, text: `${setup.draft?.draft.teams.length ?? 0} teams` },
    { ok: questions === 0, text: questions ? `${questions} open question(s) on the Review step` : 'No open questions' },
    { ok: Boolean(setup.schedule), text: setup.schedule ? `${setup.schedule.matches.length} matches scheduled` : 'No schedule yet' },
  ]
  const ready = setup.status === 'ready' && checks.every((c) => c.ok)
  const publish = () => action.run(async () => {
    await api.publishSetup(setup.id, setup.draft.version, policy)
    await reload()
    return null
  })

  return (
    <div className="wiz-card">
      <section className="profile-card">
        <h2>Ready to publish?</h2>
        <ul className="setup-checks">
          {checks.map((c) => <li key={c.text} className={c.ok ? 'is-ok' : 'is-missing'}>{c.ok ? '✓' : '✕'} {c.text}</li>)}
        </ul>
      </section>
      <section className="profile-card">
        <h2>Filming</h2>
        {junior && <p className="hint">🛡 Junior event: filming is only possible with consent, or not at all.</p>}
        <div className="setup-filming" role="radiogroup" aria-label="Filming policy">
          {options.map((o) => (
            <label key={o.id} className={`setup-filming-option${policy === o.id ? ' is-on' : ''}`}>
              <input type="radio" name="filming" value={o.id} checked={policy === o.id} onChange={() => setPolicy(o.id)} />
              <span><strong>{o.label}</strong><span className="hint"> — {o.text}</span></span>
            </label>
          ))}
        </div>
      </section>
      <Notice action={action} />
      <div className="wiz-nav">
        <button className="btn btn--ghost" onClick={onBack}>← Draw & schedule</button>
        <button className="btn btn--accent" disabled={!ready || action.busy} onClick={publish}>
          {action.busy ? 'Publishing…' : 'Publish — make it public'}
        </button>
      </div>
    </div>
  )
}
