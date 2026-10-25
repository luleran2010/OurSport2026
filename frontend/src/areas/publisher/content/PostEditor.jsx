import { useRef, useState } from 'react'
import { api } from '../../../api/client'
import RichText from '../../../components/RichText'
import { fromZonedInput, toZonedInput } from '../../../utils/time'

const LANG = { fi: 'Finnish', en: 'English', bn: 'Bangla' }

/** Write news (P5): title, body with basic formatting, image, linked teams / matches, language, publish time. */
export default function PostEditor({ data, post, onClose, onSaved }) {
  const editing = Boolean(post)
  const [f, setF] = useState(() => ({
    title: post?.title ?? '',
    summary: post?.summary ?? '',
    body: post ? post.body.join('\n\n') : '',
    imageUrl: post?.imageUrl ?? null,
    teamIds: post?.teamIds ?? [],
    matchIds: post?.matchIds ?? [],
    language: post?.language ?? data.languages[0],
    schedule: Boolean(post?.publishAt),
    at: post?.publishAt ? toZonedInput(post.publishAt) : '',
  }))
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [uploading, setUploading] = useState(false)
  const bodyRef = useRef(null)
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const toggle = (k, id) => set(k, f[k].includes(id) ? f[k].filter((x) => x !== id) : [...f[k], id])

  // wrap the selection in the body with **…** / *…*, or prefix the selected lines with "- "
  const format = (kind) => {
    const el = bodyRef.current
    if (!el) return
    const { selectionStart: a, selectionEnd: b, value } = el
    let next
    let caret
    if (kind === 'list') {
      const start = value.lastIndexOf('\n', a - 1) + 1
      const lines = value.slice(start, b).split('\n').map((l) => (l.startsWith('- ') ? l : `- ${l}`)).join('\n')
      next = value.slice(0, start) + lines + value.slice(b)
      caret = start + lines.length
    } else {
      const mark = kind === 'bold' ? '**' : '*'
      const sel = value.slice(a, b) || (kind === 'bold' ? 'bold text' : 'italic text')
      next = `${value.slice(0, a)}${mark}${sel}${mark}${value.slice(b)}`
      caret = a + mark.length + sel.length + mark.length
    }
    set('body', next)
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(caret, caret) })
  }

  const upload = async (file) => {
    if (!file) return
    setUploading(true)
    setErr(null)
    try {
      const r = await api.uploadImage(file)
      set('imageUrl', r.url)
    } catch (x) {
      setErr(x.message)
    } finally {
      setUploading(false)
    }
  }

  const save = async (submit) => {
    setBusy(true)
    setErr(null)
    const payload = {
      title: f.title.trim(), summary: f.summary.trim() || null, body: f.body, imageUrl: f.imageUrl, teamIds: f.teamIds,
      matchIds: f.matchIds, language: f.language, publishAt: f.schedule && f.at ? fromZonedInput(f.at) : null,
    }
    try {
      const res = editing
        ? await api.updatePost(post.id, { ...payload, ...(submit && post.status === 'draft' ? { submit: true } : {}) })
        : await api.createPost({ ...payload, eventId: data.eventId, submit })
      onSaved(res)
    } catch (x) {
      setErr(x.message)
    } finally {
      setBusy(false)
    }
  }

  const sendLabel = !data.canPublish ? 'Send to the editors' : f.schedule && f.at ? 'Schedule' : 'Publish now'
  const isLive = editing && (post.status === 'published' || post.status === 'scheduled')
  const isReview = editing && post.status === 'in_review'
  return (
    <section className="ev-card pe-editor" aria-label={editing ? 'Edit post' : 'Write news'}>
      <div className="pe-editor-head">
        <h2>{editing ? 'Edit post' : 'Write news'}</h2>
        <button className="link-btn" onClick={onClose}>Close</button>
      </div>
      {!data.canPublish && !editing && (
        <p className="ev-note">This event has no publish rights: your post goes to the OurSport editors and appears when they approve it.</p>
      )}
      {isReview && <p className="ev-note">The post is waiting for an editor. You can change it until they pick it up.</p>}
      <label className="field"><span>Headline</span>
        <input value={f.title} maxLength={140} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Semi-final day: what to know" />
      </label>
      <div className="pe-body-head">
        <span className="pe-label">Text</span>
        <div className="pe-toolbar" role="toolbar" aria-label="Formatting">
          <button type="button" onClick={() => format('bold')} title="Bold" aria-label="Bold" disabled={preview}><b>B</b></button>
          <button type="button" onClick={() => format('italic')} title="Italic" aria-label="Italic" disabled={preview}><i>I</i></button>
          <button type="button" onClick={() => format('list')} title="List" aria-label="Bulleted list" disabled={preview}>• List</button>
          <button type="button" className={preview ? 'is-active' : ''} aria-pressed={preview} onClick={() => setPreview((p) => !p)}>Preview</button>
        </div>
      </div>
      {preview ? (
        <div className="pe-preview story" lang={f.language}>
          <h1>{f.title || 'Headline'}</h1>
          {f.imageUrl && <img className="story-image" src={f.imageUrl} alt="" />}
          {f.body.split(/\n\s*\n/).filter((p) => p.trim()).map((p, i) => <RichText key={i} text={p} />)}
        </div>
      ) : (
        <textarea ref={bodyRef} className="pe-body" rows={10} value={f.body} lang={f.language} maxLength={8000}
          onChange={(e) => set('body', e.target.value)}
          placeholder={'A blank line starts a new paragraph.\n**bold**, *italic*, and lines starting with "- " make a list.'} />
      )}
      <label className="field"><span>Summary <small>(optional — the first sentence is used if empty)</small></span>
        <input value={f.summary} maxLength={300} onChange={(e) => set('summary', e.target.value)} />
      </label>

      <div className="pe-grid">
        <div className="field">
          <span>Image</span>
          {f.imageUrl ? (
            <div className="pe-image">
              <img src={f.imageUrl} alt="" />
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => set('imageUrl', null)}>Remove</button>
            </div>
          ) : (
            <label className="btn btn--ghost btn--sm pe-upload">
              {uploading ? 'Uploading…' : 'Add an image'}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="sr-only" onChange={(e) => upload(e.target.files?.[0])} />
            </label>
          )}
          <small>PNG, JPEG, WebP or GIF, up to 2 MB.</small>
        </div>
        <label className="field"><span>Language</span>
          <select value={f.language} onChange={(e) => set('language', e.target.value)}>
            {data.languages.map((l) => <option key={l} value={l}>{LANG[l]}</option>)}
          </select>
        </label>
        <div className="field">
          <span>Publish</span>
          <label className="ev-check"><input type="radio" name="when" checked={!f.schedule} onChange={() => set('schedule', false)} disabled={isLive && post.status === 'published'} /> {data.canPublish ? 'Now' : 'When approved'}</label>
          <label className="ev-check"><input type="radio" name="when" checked={f.schedule} onChange={() => set('schedule', true)} disabled={isLive && post.status === 'published'} /> At a set time</label>
          {f.schedule && <input type="datetime-local" value={f.at} onChange={(e) => set('at', e.target.value)} aria-label="Publish time (Finnish time)" />}
        </div>
      </div>

      <div className="field">
        <span>Linked teams</span>
        <div className="chips chips--wrap">
          {data.teams.map((t) => (
            <button type="button" key={t.id} className={`chip chip--sm${f.teamIds.includes(t.id) ? ' is-active' : ''}`} aria-pressed={f.teamIds.includes(t.id)}
              onClick={() => toggle('teamIds', t.id)}>{t.name}</button>
          ))}
        </div>
      </div>
      <label className="field"><span>Linked matches <small>(Ctrl/Cmd-click for more than one)</small></span>
        <select multiple size={5} value={f.matchIds} onChange={(e) => set('matchIds', [...e.target.selectedOptions].map((o) => o.value))}>
          {data.matches.map((m) => (
            <option key={m.id} value={m.id}>{m.stage ? `${m.stage}: ` : ''}{m.home.name} v {m.away.name}{m.score ? ` (${m.score[0]}–${m.score[1]})` : ''}</option>
          ))}
        </select>
      </label>

      {err && <p className="form-error" role="alert">{err}</p>}
      <div className="ev-actions-row">
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
        {(!editing || post.status === 'draft') && (
          <button type="button" className="btn btn--ghost btn--sm" disabled={busy || !f.title.trim()} onClick={() => save(false)}>Save draft</button>
        )}
        <button type="button" className="btn btn--accent btn--sm" disabled={busy || !f.title.trim() || !f.body.trim() || (f.schedule && !f.at)}
          onClick={() => save(true)}>
          {busy ? 'Saving…' : editing && post.status !== 'draft' ? 'Save changes' : sendLabel}
        </button>
      </div>
    </section>
  )
}
