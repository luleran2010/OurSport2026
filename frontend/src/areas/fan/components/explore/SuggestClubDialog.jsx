import { useEffect, useRef, useState } from 'react'
import { api } from '../../../../api/client'
import { useCatalog } from '../../../../app/providers/catalog'

export default function SuggestClubDialog({ open, onClose, initialName = '' }) {
  const ref = useRef(null)
  const { sports } = useCatalog()
  const [status, setStatus] = useState('idle') // idle | sending | sent | error
  const [error, setError] = useState('')

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const submit = async (e) => {
    e.preventDefault()
    const form = Object.fromEntries(new FormData(e.currentTarget))
    setStatus('sending')
    try {
      await api.suggestClub(form)
      setStatus('sent')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  const close = () => {
    setStatus('idle')
    onClose()
  }

  return (
    <dialog ref={ref} className="modal" onClose={close} aria-labelledby="suggest-h">
      {status === 'sent' ? (
        <div className="modal-body">
          <h2 id="suggest-h">Thanks!</h2>
          <p className="page-sub">We’ll check the club and add it to OurSport AI soon.</p>
          <div className="modal-actions">
            <button className="btn btn--accent" onClick={close}>Done</button>
          </div>
        </div>
      ) : (
        <form className="modal-body" onSubmit={submit}>
          <h2 id="suggest-h">Suggest a club</h2>
          <p className="page-sub">Can’t find your club? Tell us about it and we’ll add it.</p>
          <label className="field">
            <span>Club name *</span>
            <input name="name" required minLength={2} maxLength={120} defaultValue={initialName} autoFocus />
          </label>
          <div className="field-row">
            <label className="field">
              <span>Town or city</span>
              <input name="city" maxLength={80} />
            </label>
            <label className="field">
              <span>Sport</span>
              <select name="sport" defaultValue="">
                <option value="">Choose…</option>
                {sports.filter((s) => s.id !== 'all').map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
                <option value="other">Other</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>Your email (optional)</span>
            <input name="contact" type="email" maxLength={120} placeholder="So we can tell you when it’s live" />
          </label>
          <label className="field">
            <span>Anything else?</span>
            <textarea name="message" rows={3} maxLength={1000} placeholder="Website, teams, where they play…" />
          </label>
          {status === 'error' && <p className="form-error" role="alert">{error || 'Something went wrong.'}</p>}
          <div className="modal-actions">
            <button type="button" className="btn btn--ghost" onClick={close}>Cancel</button>
            <button className="btn btn--accent" disabled={status === 'sending'}>
              {status === 'sending' ? 'Sending…' : 'Send suggestion'}
            </button>
          </div>
        </form>
      )}
    </dialog>
  )
}
