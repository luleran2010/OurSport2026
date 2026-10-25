import { useState } from 'react'
import { api } from '../../../api/client'
import { STATUS, useAction } from './setup'

// Small components the setup wizard steps share.

export function Notice({ action }) {
  if (action.error) return <p className="form-error" role="alert">{action.error}</p>
  if (action.ok) return <p className="form-ok" role="status">{action.ok}</p>
  return null
}

export function StatusPill({ status }) {
  const s = STATUS[status] ?? { label: status, tone: 'muted' }
  return <span className={`pub-status pub-status--${s.tone}`}>{s.label}</span>
}

/** Remove an event that was never published (its uploads and drafts go too), after a confirmation. */
export function RemoveEvent({ setup, onRemoved }) {
  const [asking, setAsking] = useState(false)
  const action = useAction(() => {}, async () => {})
  if (setup.status === 'published') return null
  const remove = () => action.run(async () => {
    await api.deleteSetup(setup.id)
    onRemoved()
    return null
  })
  if (!asking) return <button className="link-btn pub-remove" onClick={() => setAsking(true)}>Remove</button>
  return (
    <div className="pub-remove-confirm" role="alertdialog" aria-label={`Remove ${setup.tournament?.name ?? 'this event'}`}>
      <span>Remove <strong>{setup.tournament?.name ?? 'this event'}</strong>? Its uploads, drafts and schedule are deleted. Nothing was published.</span>
      <button className="btn btn--ghost btn--sm" onClick={() => setAsking(false)} disabled={action.busy}>Cancel</button>
      <button className="btn btn--danger btn--sm" onClick={remove} disabled={action.busy} autoFocus>{action.busy ? 'Removing…' : 'Remove'}</button>
      <Notice action={action} />
    </div>
  )
}
