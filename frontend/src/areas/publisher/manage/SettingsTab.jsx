import { useState } from 'react'
import { api } from '../../../api/client'

const LANGS = [['fi', 'Finnish'], ['en', 'English'], ['bn', 'Bangla']]
const VIS = [
  ['public', 'Public', 'Listed in Events and search; anyone can open it.'],
  ['unlisted', 'Unlisted', 'Not listed; people with the link can open it.'],
  ['hidden', 'Hidden', 'Fans can’t open it. Scores are still kept.'],
]

export default function SettingsTab({ d, eventId, reload }) {
  const [f, setF] = useState(d.settings)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const dirty = JSON.stringify([f.languages, f.reviewEnabled, f.visibility]) !== JSON.stringify([d.settings.languages, d.settings.reviewEnabled, d.settings.visibility])
  const toggleLang = (l) => setF({ ...f, languages: f.languages.includes(l) ? f.languages.filter((x) => x !== l) : [...f.languages, l] })
  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      await api.patchEvent(eventId, { languages: f.languages, reviewEnabled: f.reviewEnabled, visibility: f.visibility })
      setMsg({ tone: 'ok', text: 'Settings saved.' })
      reload()
    } catch (x) {
      setMsg({ tone: 'error', text: x.message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="ev-settings" onSubmit={save}>
      <fieldset className="ev-card">
        <legend>Content languages</legend>
        <p className="page-sub">AI texts are written in these languages, and your posts can use them.</p>
        <div className="ev-checks">
          {LANGS.map(([id, label]) => (
            <label key={id} className="ev-check"><input type="checkbox" checked={f.languages.includes(id)} onChange={() => toggleLang(id)}
              disabled={f.languages.length === 1 && f.languages.includes(id)} /> {label}</label>
          ))}
        </div>
      </fieldset>
      <fieldset className="ev-card">
        <legend>Publisher review</legend>
        <label className="ev-check">
          <input type="checkbox" checked={f.reviewEnabled} onChange={(e) => setF({ ...f, reviewEnabled: e.target.checked })} />
          I review AI texts before they’re published
        </label>
        <p className="page-sub">Off: AI texts go out after the automatic fact check (flagged ones still go to the OurSport editors).</p>
      </fieldset>
      <fieldset className="ev-card">
        <legend>Visibility</legend>
        {VIS.map(([id, label, text]) => (
          <label key={id} className="ev-radio">
            <input type="radio" name="vis" checked={f.visibility === id} onChange={() => setF({ ...f, visibility: id })} />
            <span><b>{label}</b><span className="ev-sub">{text}</span></span>
          </label>
        ))}
      </fieldset>
      <fieldset className="ev-card">
        <legend>Publish rights</legend>
        <p>{d.settings.canPublish ? '✓ Your news posts are published directly.' : 'Your news posts go to the OurSport editors before they appear.'}</p>
        <p className="page-sub">{d.junior ? 'Junior events always get an editor’s check. ' : ''}Publish rights are set by OurSport.</p>
      </fieldset>
      {msg && <p className={msg.tone === 'error' ? 'form-error' : 'ev-ok'} role="status">{msg.text}</p>}
      <div className="ev-actions-row">
        <button className="btn btn--accent" disabled={busy || !dirty}>{busy ? 'Saving…' : 'Save settings'}</button>
      </div>
    </form>
  )
}
