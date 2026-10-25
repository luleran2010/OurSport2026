import { useState } from 'react'
import { api } from '../../../api/client'
import { formatDate } from '../../../utils/time'

const STATUS = { active: ['Active', 'ok'], invited: ['Invited', 'warn'], expired: ['Expired', 'off'] }

export default function ScorersTab({ d, eventId, reload }) {
  const [emails, setEmails] = useState('')
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)
  const [removing, setRemoving] = useState(null)
  const list = emails.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean)

  const invite = async (addrs, who = null) => {
    setBusy(true)
    setErr(null)
    setResult(null)
    try {
      const r = await api.inviteEventScorers(eventId, { emails: addrs, name: (who ?? name).trim() || null, message: message.trim() || null })
      setResult(r)
      if (!who) { setEmails(''); setName('') }
      reload()
    } catch (x) {
      setErr(x.message)
    } finally {
      setBusy(false)
    }
  }
  const remove = async (s) => {
    setBusy(true)
    try {
      await api.removeEventScorer(eventId, s.id)
      setRemoving(null)
      reload()
    } catch (x) {
      setErr(x.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ev-scorers">
      <form className="ev-card" onSubmit={(e) => { e.preventDefault(); if (list.length) invite(list) }}>
        <h3>Invite scorers</h3>
        <p className="page-sub">
          They get an email with a link to the scorer app. The invite turns active when they log in with the same email; it expires after 14 days.
          Volunteers don’t need to be club members.
        </p>
        <div className="ev-add-row">
          <label className="field ev-grow"><span>Emails <small>(one or more, separated by commas or spaces)</small></span>
            <textarea rows={2} value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="anna@example.org, mikko@example.org" />
          </label>
          {list.length <= 1 && (
            <label className="field"><span>Name <small>(optional)</small></span><input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
          )}
        </div>
        <label className="field"><span>Message <small>(optional, in the email)</small></span>
          <input value={message} maxLength={500} onChange={(e) => setMessage(e.target.value)} placeholder="Thanks for helping on match day!" />
        </label>
        {err && <p className="form-error" role="alert">{err}</p>}
        {result && (
          <p className="ev-ok" role="status">
            {result.invited.length ? `Invited: ${result.invited.map((s) => s.email).join(', ')}.` : 'Nobody new was invited.'}
            {result.skipped.map((s) => ` ${s.email}: ${s.reason}`).join('')}
          </p>
        )}
        <div className="ev-actions-row">
          <button className="btn btn--accent btn--sm" disabled={busy || !list.length}>
            {busy ? 'Sending…' : `Send ${list.length > 1 ? `${list.length} invites` : 'invite'}`}
          </button>
        </div>
      </form>

      <table className="ev-table">
        <thead><tr><th>Scorer</th><th>Status</th><th>Invited</th><th className="num">Matches</th><th aria-label="Actions" /></tr></thead>
        <tbody>
          {d.scorers.length === 0 && <tr><td colSpan={5} className="page-sub">No scorers yet. Invite volunteers above, then pick them per match in Fixtures.</td></tr>}
          {d.scorers.map((s) => {
            const [label, tone] = STATUS[s.status]
            return (
              <tr key={s.id}>
                <td><b>{s.name ?? '—'}</b><span className="ev-sub">{s.email}</span></td>
                <td><span className={`ev-pill ev-pill--${tone}`}>{label}</span>{s.acceptedAt && <span className="ev-sub">since {formatDate(s.acceptedAt)}</span>}</td>
                <td className="ev-sub">{formatDate(s.invitedAt)}{s.status === 'invited' && s.expiresAt ? ` · expires ${formatDate(s.expiresAt)}` : ''}</td>
                <td className="num">{s.matches}</td>
                <td className="ev-row-actions">
                  {s.status !== 'active' && <button className="btn btn--ghost btn--sm" disabled={busy} onClick={() => invite([s.email], s.name ?? '')}>Resend</button>}
                  {removing === s.id ? (
                    <>
                      <button className="btn btn--danger btn--sm" disabled={busy} onClick={() => remove(s)}>{s.status === 'active' ? 'Remove' : 'Cancel invite'}</button>
                      <button className="btn btn--ghost btn--sm" onClick={() => setRemoving(null)}>Keep</button>
                    </>
                  ) : (
                    <button className="btn btn--ghost btn--sm ev-danger" onClick={() => setRemoving(s.id)}>{s.status === 'active' ? 'Remove' : 'Cancel'}</button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {d.scorers.some((s) => s.matches > 0) && <p className="page-sub">Removing a scorer takes them off the matches that haven’t finished.</p>}
    </div>
  )
}
