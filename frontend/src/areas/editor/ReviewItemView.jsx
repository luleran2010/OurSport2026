import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { api } from '../../api/client'
import { useLoad } from '../../api/useLoad'
import { clockTime, formatDateTime } from '../../utils/time'

const REASON_LABEL = {
  sensitive_topic: 'Sensitive topic', blocked_claim: 'Blocked claim', junior_mention: 'Junior mention',
  manual_news: 'Manual news', correction: 'Correction',
}
const ACTION_LABEL = {
  generated: 'Generated', submitted: 'Submitted', published: 'Published', reported: 'Error reported', checked: 'Checker ran',
  claimed: 'Claimed', edited: 'Edited', approved: 'Approved', rejected: 'Rejected', sent_back: 'Sent back to regenerate',
  regenerated: 'New version', corrected: 'Corrected',
}
const SHORTCUTS = [
  ['j', 'Next item'], ['k', 'Previous item'], ['a', 'Approve and publish'], ['e', 'Edit then approve'], ['r', 'Reject'],
  ['s', 'Send back to regenerate'], ['u', 'Back to the queue'], ['Esc', 'Cancel'], ['?', 'Shortcuts'],
]

function typing(el) {
  return el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

function allSentences(a) {
  return a ? [a.title, ...a.summary, ...a.body.flat()] : []
}

/** One sentence: underlined when tied to facts, red when the checker flagged it; hover shows the fact ids and flags. */
function Sentence({ s, litFact, onHover }) {
  const tip = [s.factIds.length ? `Facts: ${s.factIds.join(', ')}` : 'Not tied to any fact', ...s.flags.map((f) => `⚑ ${f.reason}`)].join('\n')
  const lit = litFact && s.factIds.includes(litFact)
  return (
    <>
      <span
        className={`sent${s.factIds.length ? ' sent--facts' : ''}${s.flags.length ? ' sent--flag' : ''}${lit ? ' is-lit' : ''}`}
        data-tip={tip} id={`sent-${s.id}`} tabIndex={0}
        onMouseEnter={() => onHover(s.factIds)} onMouseLeave={() => onHover([])} onFocus={() => onHover(s.factIds)}
        onBlur={() => onHover([])}
      >
        {s.text}
      </span>
      {s.flags.map((f, i) => (
        <span key={i} className={`flag-note flag-note--${f.code}`}>⚑ {f.reason}</span>
      ))}{' '}
    </>
  )
}

function TextView({ d, litFact, onHover }) {
  const a = d.annotated
  return (
    <article className="ri-text" lang={d.language}>
      <h2 className="ri-title"><Sentence s={a.title} litFact={litFact} onHover={onHover} /></h2>
      {a.summary.length > 0 && (
        <p className="ri-summary">{a.summary.map((s) => <Sentence key={s.id} s={s} litFact={litFact} onHover={onHover} />)}</p>
      )}
      {a.body.map((par, i) => (
        <p key={i}>{par.map((s) => <Sentence key={s.id} s={s} litFact={litFact} onHover={onHover} />)}</p>
      ))}
    </article>
  )
}

function CheckChip({ check }) {
  if (!check) return null
  if (check.status === 'stale') return <span className="ri-chip ri-chip--stale">Text changed — not checked yet</span>
  if (check.status === 'passed') return <span className="ri-chip ri-chip--ok">✓ Checker passed · {clockTime(check.at)}</span>
  return <span className="ri-chip ri-chip--bad">⚑ {check.flags} red flag{check.flags === 1 ? '' : 's'} · checked {clockTime(check.at)}</span>
}

function MatchCard({ m, eventName }) {
  if (!m) return <p className="desk-muted">No match: this text isn’t about one game.{eventName ? ` Event: ${eventName}.` : ''}</p>
  const score = m.score ? `${m.score[0]}–${m.score[1]}` : 'v'
  return (
    <dl className="ri-kv">
      <div><dt>Match</dt><dd><b>{m.home.name} {score} {m.away.name}</b></dd></div>
      <div><dt>Status</dt><dd>{m.status === 'finished' ? 'Finished' : m.status === 'live' ? `Live${m.period ? ` · ${m.period}` : ''}` : 'Upcoming'}
        {m.correction ? ' · corrected' : ''}</dd></div>
      <div><dt>Competition</dt><dd>{m.league}{m.stage ? ` · ${m.stage}` : ''}{eventName ? ` · ${eventName}` : ''}</dd></div>
      <div><dt>{m.status === 'finished' ? 'Ended' : 'Starts'}</dt><dd>{formatDateTime(m.endedAt ?? m.startsAt)}</dd></div>
      <div><dt>Venue</dt><dd>{m.venue}</dd></div>
      <div><dt>Data</dt><dd>{m.dataLevel === 'results_only' ? 'Final score only (no live events)' : 'Live scorer events'}</dd></div>
    </dl>
  )
}

/** E2 Review item: the text with the checker's marks on the left, the evidence on the right, the decision in the footer. */
export default function ReviewItemView({ itemId, onNavigate }) {
  const location = useLocation()
  const [kick, setKick] = useState(0)
  const state = useLoad(() => api.reviewItem(itemId), `${itemId}#${kick}`)
  const d = state.data
  const [hot, setHot] = useState(() => new Set()) // facts of the hovered sentence -> lit rows in the fact sheet
  const [litFact, setLitFact] = useState(null) // hovered fact row -> lit sentences that use it
  const [mode, setMode] = useState('view') // view | edit
  const [approveAfterSave, setApproveAfterSave] = useState(false)
  const [form, setForm] = useState(null)
  const [panel, setPanel] = useState(null) // null | reject | regenerate
  const [reason, setReason] = useState('')
  const [verified, setVerified] = useState(false)
  const [publicNote, setPublicNote] = useState('') // corrections: what was corrected, shown to readers
  const publicRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(location.state?.flash ? { tone: 'ok', text: location.state.flash } : null)
  const [help, setHelp] = useState(false)
  const titleRef = useRef(null)
  const reasonRef = useRef(null)

  const reload = () => setKick((k) => k + 1)
  const sid = d ? d.storyId ?? d.id : null
  const open = d && d.status !== 'decided' && d.status !== 'regenerating'
  const mineOrFree = d && (!d.assignedTo || d.assignedToMe)
  const canAct = open && mineOrFree && !busy
  const flags = d?.check?.status === 'flagged' ? d.check.flags : 0

  // While the AI writer works on a new version, look again when it should be back.
  const regenAt = d?.status === 'regenerating' ? d.regenerateAt - d.updatedAt : null
  useEffect(() => {
    if (regenAt === null) return
    const t = setTimeout(() => setKick((k) => k + 1), Math.max(regenAt, 0) + 600)
    return () => clearTimeout(t)
  }, [regenAt])

  const go = (id, flash) => onNavigate(id ? { type: 'editor', itemId: id } : { type: 'editor' }, flash ? { state: { flash } } : undefined)
  // an editor's own correction (E3 "Correct") comes from and returns to the published list
  const isFix = d?.kind === 'fix'
  const correcting = d && (isFix || (d.kind === 'correction' && d.text))
  const fromPublished = isFix || location.state?.from === 'published'
  const back = (flash) => (fromPublished ? onNavigate({ type: 'editor', section: 'published' }, flash ? { state: { flash } } : undefined) : go(null, flash))
  const needsNote = isFix && publicNote.trim().length < 5

  const fail = (err) => {
    setMsg({ tone: 'error', text: err.message || 'Something went wrong.' })
    if (['claimed', 'decided', 'stale_version', 'check_stale', 'regenerating'].includes(err.code)) reload()
  }

  const run = async (fn) => {
    if (busy) return
    setBusy(true)
    setMsg(null)
    try {
      await fn()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (thenApprove) => {
    if (!canAct || !d.text) return
    setForm({ title: d.text.title, summary: d.text.summary ?? '', body: d.text.body.join('\n\n') })
    setApproveAfterSave(thenApprove)
    setPanel(null)
    setMode('edit')
    setTimeout(() => titleRef.current?.focus(), 0)
  }

  // "I verified this manually" stands in for the checker: approve with flags left or without a check
  const approve = () => run(async () => {
    if (d.check?.status === 'stale' && !verified) throw Object.assign(new Error('The text changed since the last check. Run the checker, or tick “I verified this manually”.'), { code: 'x' })
    if (flags && !verified) {
      throw Object.assign(new Error(`${flags} red flag${flags === 1 ? '' : 's'} left. Fix the text, or tick “I verified this manually”.`), { code: 'x' })
    }
    if (needsNote) {
      publicRef.current?.focus()
      throw Object.assign(new Error('Say what was corrected — readers see this note.'), { code: 'x' })
    }
    const res = await api.approveStory(sid, { itemId: d.id, verified, publicNote: publicNote.trim() || undefined })
    if (isFix) back(`Correction published: “${d.text.title}”. Readers see “Corrected on …”.`)
    else if (fromPublished) back(`Approved and published: “${d.text?.title ?? d.item?.headline}”.`)
    else go(res.nextId, `Approved and published: “${d.text?.title ?? d.item?.headline}”.`)
  })

  const saveAndCheck = () => run(async () => {
    const body = form.body.split(/\n\s*\n/).map((p) => p.replace(/\s*\n\s*/g, ' ').trim()).filter(Boolean)
    await api.editStory(sid, { itemId: d.id, version: d.version, title: form.title, summary: form.summary.trim() || null, body })
    if (approveAfterSave && verified && !needsNote) { // verified by the editor: no checker run
      const res = await api.approveStory(sid, { itemId: d.id, verified, publicNote: publicNote.trim() || undefined })
      if (isFix) back(`Correction published: “${form.title}”. Readers see “Corrected on …”.`)
      else if (fromPublished) back(`Edited and published (verified manually): “${form.title}”.`)
      else go(res.nextId, `Edited and published (verified manually): “${form.title}”.`)
      return
    }
    const checked = await api.checkStory(sid, d.id)
    setMode('view')
    if (approveAfterSave && checked.check.status === 'passed' && !needsNote) {
      const res = await api.approveStory(sid, { itemId: d.id, publicNote: publicNote.trim() || undefined })
      if (isFix) back(`Correction published: “${form.title}”. Readers see “Corrected on …”.`)
      else if (fromPublished) back(`Edited, checked and published: “${form.title}”.`)
      else go(res.nextId, `Edited, checked and published: “${form.title}”.`)
      return
    }
    if (approveAfterSave && checked.check.status === 'passed' && needsNote) {
      reload()
      setMsg({ tone: 'ok', text: 'Saved and the checker passed. Add the note for readers, then publish the correction.' })
      setTimeout(() => publicRef.current?.focus(), 0)
      return
    }
    reload()
    setMsg(checked.check.status === 'passed'
      ? { tone: 'ok', text: 'Saved. The checker passed — approve when ready.' }
      : { tone: 'error', text: `Saved, but the checker found ${checked.check.flags} red flag${checked.check.flags === 1 ? '' : 's'}${approveAfterSave ? ', so it wasn’t published' : ''}.` })
  })

  const runCheck = () => run(async () => {
    const c = await api.checkStory(sid, d.id)
    reload()
    setMsg(c.check.status === 'passed' ? { tone: 'ok', text: 'The checker passed.' } : { tone: 'error', text: `${c.check.flags} red flag(s).` })
  })

  const submitPanel = () => run(async () => {
    const text = reason.trim()
    if (panel === 'regenerate' && text.length < 5) {
      reasonRef.current?.focus()
      throw Object.assign(new Error('Tell the writer what to change.'), { code: 'x' })
    }
    if (panel === 'reject') {
      const res = await api.rejectStory(sid)
      go(res.nextId, `Rejected: “${d.text?.title ?? d.item?.headline}”.`)
    } else {
      const res = await api.regenerateStory(sid, { itemId: d.id, note: text })
      if (res.held) {
        reload()
        setPanel(null)
        setMsg({ tone: 'error', text: 'The AI writer rewrote it, but the checker still holds the new version. Review it again.' })
      } else {
        go(res.nextId, 'Rewritten by the AI writer: the new version passed the checker and is published.')
      }
    }
  })

  const openPanel = (p) => {
    if (!canAct) return
    setMode('view')
    setPanel(p)
    setReason('')
    setTimeout(() => reasonRef.current?.focus(), 0)
  }

  const onKey = useEffectEvent((e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || !d) return
    if (e.key === 'Escape') {
      if (help) setHelp(false)
      else if (panel) setPanel(null)
      else if (mode === 'edit') setMode('view')
      else if (typing(document.activeElement)) document.activeElement.blur()
      return
    }
    if (typing(document.activeElement)) return
    const k = e.key.toLowerCase()
    if (k === 'j' && d.nav.nextId) go(d.nav.nextId)
    else if (k === 'k' && d.nav.prevId) go(d.nav.prevId)
    else if (k === 'u') back()
    else if (k === '?') setHelp((h) => !h)
    else if (mode === 'edit' || panel) return
    else if (k === 'a' && canAct) approve()
    else if (k === 'e') { e.preventDefault(); startEdit(true) }
    else if (k === 'r' && !isFix) { e.preventDefault(); openPanel('reject') }
    else if (k === 's' && d.text && !isFix) { e.preventDefault(); openPanel('regenerate') }
  })
  useEffect(() => {
    const h = (e) => onKey(e)
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  if (!d) {
    if (state.status === 'error') {
      return (
        <div className="desk-page">
          <p className="form-error" role="alert">{state.error?.status === 404 ? 'This item isn’t in the queue any more.' : state.error?.message}</p>
          <button className="link-btn link-btn--accent" onClick={() => go(null)}>← Review queue</button>{' '}
          <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'editor', section: 'published' })}>Published content</button>
        </div>
      )
    }
    return <div className="desk-page" aria-busy="true"><span className="spinner" /> Loading…</div>
  }

  const it = d.item
  const sents = allSentences(d.annotated)
  const flagged = sents.filter((s) => s.flags.length)

  return (
    <div className="ri">
      <div className="ri-bar">
        <button className="link-btn" onClick={() => back()} title="Back (u)">{fromPublished ? '← Published' : '← Queue'}</button>
        {isFix && <span className="desk-reason desk-reason--correction">Editor’s correction</span>}
        {it && <span className={`desk-prio desk-prio--${it.priority}`}>{it.priority === 'high' ? 'High' : 'Normal'}</span>}
        {it && <span className={`desk-reason desk-reason--${it.reason}`}>{REASON_LABEL[it.reason]}</span>}
        <span className="desk-muted">{d.tag ?? (d.kind === 'correction' ? 'Correction' : '')} · {d.author ?? ''} · {d.language.toUpperCase()} · v{d.version}</span>
        <CheckChip check={d.check} />
        <span className="desk-spacer" />
        <span className="desk-muted">
          {d.assignedToMe ? <b className="desk-me">Assigned to you</b> : d.assignedTo ? `Assigned to ${d.assignedTo}` : 'Unassigned'}
        </span>
        <span className="ri-nav">
          <button className="btn btn--ghost btn--sm" disabled={!d.nav.prevId} onClick={() => go(d.nav.prevId)} title="Previous item (k)">‹ <kbd>k</kbd></button>
          <span className="desk-muted">{d.nav.position ? `${d.nav.position} / ${d.nav.total}` : `– / ${d.nav.total}`}</span>
          <button className="btn btn--ghost btn--sm" disabled={!d.nav.nextId} onClick={() => go(d.nav.nextId)} title="Next item (j)"><kbd>j</kbd> ›</button>
        </span>
        <button className="btn btn--ghost btn--sm" onClick={() => setHelp((h) => !h)} aria-expanded={help}><kbd>?</kbd></button>
      </div>

      {help && (
        <div className="desk-help ri-help" role="dialog" aria-label="Keyboard shortcuts">
          <dl>{SHORTCUTS.map(([k, v]) => <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>)}</dl>
        </div>
      )}

      {msg && (
        <p className={`ri-msg ri-msg--${msg.tone}`} role={msg.tone === 'error' ? 'alert' : 'status'}>
          {msg.text} <button className="link-btn" onClick={() => setMsg(null)} aria-label="Dismiss">×</button>
        </p>
      )}
      {d.status === 'decided' && (
        <p className={`ri-msg ri-msg--${d.decision.action === 'approved' ? 'ok' : 'error'}`}>
          {d.decision.action === 'approved' ? 'Approved' : 'Rejected'} by {d.decision.by} at {clockTime(d.decision.at)}
          {d.decision.note ? ` — ${d.decision.note}` : ''}
        </p>
      )}
      {d.status === 'regenerating' && (
        <p className="ri-msg ri-msg--info"><span className="spinner" /> Sent back to the AI writer — the new version arrives in a few seconds.</p>
      )}
      {open && d.assignedTo && !d.assignedToMe && (
        <p className="ri-msg ri-msg--info">
          {d.assignedTo} is reviewing this item. You can read it; the decision is theirs.
        </p>
      )}

      <div className="ri-cols">
        <section className="ri-left" aria-label="Text">
          {mode === 'edit' ? (
            <div className="ri-edit">
              <label className="field"><span>Headline</span>
                <input ref={titleRef} value={form.title} maxLength={160} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </label>
              <label className="field"><span>Summary</span>
                <textarea rows={2} value={form.summary} maxLength={400} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
              </label>
              <label className="field"><span>Text <small className="desk-muted">(blank line between paragraphs)</small></span>
                <textarea rows={14} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} lang={d.language} />
              </label>
            </div>
          ) : d.annotated ? (
            <>
              {flagged.length > 0 && (
                <div className="ri-flags">
                  <b>Red flags</b>
                  <ul>
                    {flagged.flatMap((s) => s.flags.map((f, i) => (
                      <li key={`${s.id}-${i}`}>
                        <button className="link-btn" onClick={() => document.getElementById(`sent-${s.id}`)?.focus()}>
                          “{f.quote}”</button> — {f.reason}
                      </li>
                    )))}
                  </ul>
                </div>
              )}
              <TextView d={d} litFact={litFact} onHover={(ids) => setHot(new Set(ids))} />
              <p className="ri-legend desk-muted">
                <span className="sent sent--facts">Underlined</span>: tied to facts (hover to see which) ·{' '}
                <span className="sent sent--flag">red</span>: flagged by the checker
              </p>
            </>
          ) : (
            <p className="desk-muted">This report is about match data, not a text. Check the data on the right, then accept (approve) or reject it.</p>
          )}
        </section>

        <aside className="ri-right" aria-label="Evidence">
          {d.correction && (
            <section className="ri-card ri-card--report">
              <h3>Reported error</h3>
              <p>“{d.correction.message}”</p>
              <p className="desk-muted">
                {d.correction.source === 'fan' ? 'Fan report' : d.correction.reporter} · {d.correction.field}
                {d.correction.correctValue ? ` · correct value: ${d.correction.correctValue}` : ''} · {formatDateTime(d.correction.createdAt)}
              </p>
            </section>
          )}
          <section className="ri-card">
            <h3>Fact sheet <span className="desk-muted">({d.facts.length})</span></h3>
            {d.facts.length ? (
              <table className="ri-facts">
                <thead><tr><th>ID</th><th>Claim</th><th>Value</th><th>Source</th></tr></thead>
                <tbody>
                  {d.facts.map((f) => (
                    <tr key={f.id} className={hot.has(f.id) || litFact === f.id ? 'is-lit' : ''}
                      onMouseEnter={() => setLitFact(f.id)} onMouseLeave={() => setLitFact(null)}>
                      <td className="ri-fid">{f.id}</td>
                      <td>{f.claim}{f.junior && <span className="ri-junior">Junior</span>}</td>
                      <td>{f.value}</td>
                      <td className="desk-muted">{f.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="desk-muted">No facts: the writer had no data for this text.</p>}
          </section>
          <section className="ri-card">
            <h3>Match data</h3>
            <MatchCard m={d.match} eventName={d.eventName} />
          </section>
          <section className="ri-card">
            <h3>Rules</h3>
            {d.ruleVersion ? (
              <p>
                <b>{d.ruleVersion.name} · version {d.ruleVersion.version}</b>
                <span className="desk-sub">Confirmed {formatDateTime(d.ruleVersion.confirmedAt)} by {d.ruleVersion.confirmedBy}</span>
                {d.ruleVersion.summary && <span className="desk-sub">{d.ruleVersion.summary}</span>}
              </p>
            ) : <p className="desk-muted">No event rules used (league match or club news).</p>}
          </section>
          <section className="ri-card">
            <h3>History</h3>
            <ol className="ri-history">
              {d.history.map((h, i) => (
                <li key={i} className={`ri-h ri-h--${h.action}`}>
                  <span className="ri-h-time">{formatDateTime(h.at)}</span>
                  <span><b>{ACTION_LABEL[h.action] ?? h.action}</b> · {h.by}{h.note ? <span className="desk-sub">{h.note}</span> : null}</span>
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>

      {open && (
        <footer className="ri-foot">
          {mode === 'edit' ? (
            <>
              <span className="desk-muted">{approveAfterSave && verified
                ? 'Verified manually: saving publishes it without the checker.'
                : `Saving re-runs the checker${approveAfterSave ? ' and publishes only if it passes' : ''}.`}</span>
              {correcting && (
                <input className="ri-override-note ri-public-note" value={publicNote} maxLength={300} onChange={(e) => setPublicNote(e.target.value)}
                  placeholder={isFix ? 'What was corrected? (shown to readers, required)' : 'Note for readers (optional)'} aria-label="Correction note shown to readers" />
              )}
              <span className="desk-spacer" />
              <button className="btn btn--ghost btn--sm" onClick={() => setMode('view')} disabled={busy}>Cancel <kbd>Esc</kbd></button>
              <label className="ri-check"><input type="checkbox" checked={approveAfterSave} onChange={(e) => setApproveAfterSave(e.target.checked)} /> Approve after saving</label>
              {approveAfterSave && (
                <label className="ri-check"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> I verified this manually</label>
              )}
              <button className="btn btn--accent btn--sm" onClick={saveAndCheck} disabled={busy}>
                {busy ? 'Saving…' : !approveAfterSave ? 'Save and check' : verified ? 'Save and approve' : 'Save, check and approve'}
              </button>
            </>
          ) : panel === 'reject' ? (
            <>
              <span><b>Reject this story?</b> <span className="desk-muted">It is not published and leaves the queue.</span></span>
              <span className="desk-spacer" />
              <button className="btn btn--ghost btn--sm" onClick={() => setPanel(null)} disabled={busy}>Cancel <kbd>Esc</kbd></button>
              <button ref={reasonRef} className="btn btn--sm btn--danger" onClick={submitPanel} disabled={busy || !mineOrFree}>Reject</button>
            </>
          ) : panel ? (
            <>
              <label className="ri-reason">
                <span>Note for the AI writer (required)</span>
                <input ref={reasonRef} value={reason} maxLength={600} onChange={(e) => setReason(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submitPanel()} placeholder="e.g. Leave out the players’ names" />
              </label>
              <button className="btn btn--ghost btn--sm" onClick={() => setPanel(null)} disabled={busy}>Cancel <kbd>Esc</kbd></button>
              <button className="btn btn--sm btn--accent" onClick={submitPanel} disabled={busy || !mineOrFree}>Send back</button>
            </>
          ) : (
            <>
              {d.check?.status === 'stale' && (
                <button className="btn btn--ghost btn--sm" onClick={runCheck} disabled={!canAct}>Run checker</button>
              )}
              {(flags > 0 || d.check?.status === 'stale') && (
                <div className="ri-override">
                  <label className="ri-check">
                    <input type="checkbox" checked={verified} disabled={!canAct} onChange={(e) => setVerified(e.target.checked)} />
                    I verified this manually
                  </label>
                </div>
              )}
              {correcting && (
                <input ref={publicRef} className="ri-override-note ri-public-note" value={publicNote} maxLength={300} disabled={!canAct}
                  onChange={(e) => setPublicNote(e.target.value)}
                  placeholder={isFix ? 'What was corrected? (shown to readers, required)' : 'Note for readers (optional)'}
                  aria-label="Correction note shown to readers" />
              )}
              <span className="desk-spacer" />
              {d.text && !isFix && <button className="btn btn--ghost btn--sm" onClick={() => openPanel('regenerate')} disabled={!canAct}>Send back to regenerate <kbd>s</kbd></button>}
              {isFix
                ? <button className="btn btn--ghost btn--sm" onClick={() => back()}>Discard</button>
                : <button className="btn btn--ghost btn--sm ri-reject" onClick={() => openPanel('reject')} disabled={!canAct}>Reject <kbd>r</kbd></button>}
              {d.text && <button className="btn btn--ghost btn--sm" onClick={() => startEdit(true)} disabled={!canAct}>Edit then approve <kbd>e</kbd></button>}
              <button className="btn btn--accent btn--sm" onClick={approve}
                disabled={!canAct || needsNote || ((flags > 0 || d.check?.status === 'stale') && !verified)}
                title={(flags > 0 || d.check?.status === 'stale') && !verified ? 'Fix the red flags or run the checker, or tick “I verified this manually”' : 'Approve and publish (a)'}>
                {isFix ? 'Publish correction' : correcting ? 'Approve and publish correction' : 'Approve and publish'} <kbd>a</kbd>
              </button>
            </>
          )}
        </footer>
      )}
    </div>
  )
}
