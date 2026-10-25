import { useState } from 'react'
import { api } from '../../../api/client'
import { Notice } from './shared'
import { useAction } from './setup'
import { TEMPLATES, rulebook, teamList } from './templates'

// Step 2: the rulebook first. The backend reads teams only from team lists, so the rulebook also
// goes in as one: when it names the teams, nothing else is needed. When it doesn't, the draft asks
// for them (open question "teams") and this step asks for the team list before moving on.

const REMOVED = { email: 'email addresses', phone: 'phone numbers', date: 'dates of birth', address: 'addresses', identity_code: 'ID numbers' }
const ACCEPT = '.csv,.txt,.xlsx,.pdf,.docx,.png,.jpg,.jpeg,text/*,image/*'

function redactionText(report) {
  const parts = Object.entries(report ?? {}).filter(([, n]) => n > 0)
    .map(([k, n]) => `${REMOVED[k] ?? k.replaceAll('_', ' ')} (${n})`)
  return parts.length ? `Removed for privacy: ${parts.join(', ')}` : 'No personal data found'
}

/** The backend reads pasted text as one team per line ("Team (Club)"); rows copied from a
 * spreadsheet go as a CSV file instead, so its table reader uses the header row and columns. */
function pastedTeams(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  const table = lines.length > 1 && lines.filter((l) => /[,;\t]/.test(l)).length >= 0.6 * lines.length
  return table ? { file: new File([text], 'teams.csv', { type: 'text/csv' }) } : { text }
}

/** A file or pasted text, not yet uploaded. */
function useInput() {
  const [state, setState] = useState({ mode: 'file', file: null, text: '', reset: 0 })
  const set = (patch) => setState((s) => ({ ...s, ...patch }))
  const given = state.mode === 'file' ? Boolean(state.file) : Boolean(state.text.trim())
  const clear = () => setState((s) => ({ ...s, file: null, text: '', reset: s.reset + 1 }))
  return { ...state, set, given, clear }
}

function DocInput({ input, label, placeholder, rows }) {
  return (
    <>
      <div className="chip-row" role="group" aria-label={`${label}: file or text`}>
        <button type="button" className={`chip chip--sm${input.mode === 'file' ? ' is-active' : ''}`} onClick={() => input.set({ mode: 'file' })}>Upload a file</button>
        <button type="button" className={`chip chip--sm${input.mode === 'text' ? ' is-active' : ''}`} onClick={() => input.set({ mode: 'text' })}>Paste text</button>
      </div>
      {input.mode === 'file' ? (
        <input key={input.reset} type="file" accept={ACCEPT} aria-label={label}
          onChange={(e) => input.set({ file: e.target.files?.[0] ?? null })} />
      ) : (
        <label className="field"><span className="visually-hidden">{label}</span>
          <textarea rows={rows} value={input.text} onChange={(e) => input.set({ text: e.target.value })} placeholder={placeholder} />
        </label>
      )}
    </>
  )
}

function FileList({ files }) {
  if (!files.length) return null
  return (
    <ul className="setup-files">
      {files.map((f) => (
        <li key={f.id}>
          <span aria-hidden="true">📄</span> {f.mime || 'text'} · {f.characters.toLocaleString()} characters
          <span className="hint"> · {redactionText(f.redaction_report)}</span>
        </li>
      ))}
    </ul>
  )
}

/** Ready-made rulebook (teams included): fills the rulebook box to look at before generating. */
function Templates({ tournament, onPick, disabled }) {
  return (
    <details className="setup-doc setup-templates">
      <summary><strong>No rulebook? Start from a template</strong></summary>
      <p className="hint">We fill in an example rulebook with teams for your dates. Change anything before you generate, or on the next steps.</p>
      <ul className="setup-template-list">
        {TEMPLATES.map((t) => (
          <li key={t.id} className="setup-template">
            <strong>{t.title}</strong>
            <span className="hint">{t.text}</span>
            <button type="button" className="btn btn--ghost btn--sm" disabled={disabled}
              onClick={() => onPick(`${rulebook(t, tournament)}\n\nTeams taking part:\n${teamList(t, tournament)}`)}>Use this template</button>
          </li>
        ))}
      </ul>
    </details>
  )
}

export default function DocumentsStep({ setup, reload, onChange, onDone }) {
  const rulesInput = useInput()
  const teamsInput = useInput()
  const [moreRules, setMoreRules] = useState(false)
  const teamsMissing = (s) => Boolean(s.draft?.open_questions.some((q) => q.field === 'teams'))
  // Rules without teams stay here for the team list; otherwise on to Review as before.
  const finish = (s) => (teamsMissing(s) ? onChange(s) : onDone(s))
  const action = useAction(finish, reload)
  const locked = setup.status === 'published'

  const rulebooks = setup.files.filter((f) => f.kind !== 'team_list')
  const lists = setup.files.filter((f) => f.kind === 'team_list')
  // The rulebook's own copy as a team list has the same size and type; anything else was added as a team list.
  const ownLists = lists.filter((l) => !rulebooks.some((r) => r.kind === 'rulebook' && r.characters === l.characters && r.mime === l.mime))
  const extracted = Boolean(setup.draft)
  const teamCount = setup.draft?.draft.teams.length ?? 0
  const needTeams = Boolean(setup.draft) && teamsMissing(setup)
  const showTeams = (rulebooks.length > 0 && needTeams) || ownLists.length > 0
  const teamsFound = extracted && !needTeams && ownLists.length === 0

  const canGenerate = rulesInput.given || teamsInput.given || (lists.length > 0 && !(needTeams && !ownLists.length))

  const upload = async () => {
    if (rulesInput.given) {
      const doc = rulesInput.mode === 'file' ? { file: rulesInput.file } : { text: rulesInput.text }
      await api.addSetupFile(setup.id, 'rulebook', doc)
      await api.addSetupFile(setup.id, 'team_list', doc)
      rulesInput.clear()
      setMoreRules(false)
    }
    if (teamsInput.given) {
      await api.addSetupFile(setup.id, 'team_list', teamsInput.mode === 'file' ? { file: teamsInput.file } : pastedTeams(teamsInput.text))
      teamsInput.clear()
    }
    await reload()
  }
  const generate = () => action.run(async () => {
    await upload()
    return api.extractSetup(setup.id)
  })
  const acceptTerms = () => action.run(async () => {
    await api.acceptProcessingTerms(setup.tournament.organisation_id)
    return api.extractSetup(setup.id)
  })

  let hint
  if (needTeams && !ownLists.length) hint = teamsInput.given ? 'Ready when you are — this takes a few seconds.' : 'Add the team list to continue.'
  else if (!canGenerate) hint = 'Add your rulebook to continue.'
  else if (extracted && !rulesInput.given && !teamsInput.given) hint = 'Added more? Generate again for a new draft.'
  else hint = 'Ready when you are — this takes a few seconds.'

  return (
    <section className="wiz-card setup-docs">
      <div className="setup-doc">
        <div className="setup-doc-head">
          <h3>Your rulebook</h3>
          {rulebooks.length > 0
            ? <span className="pub-status pub-status--done">✓ Read{teamsFound ? ` · ${teamCount} teams found in it` : ''}</span>
            : <span className="pub-status pub-status--warn">Required</span>}
        </div>
        <p className="hint">
          Format, groups, who goes through, points and tiebreakers, match length, days and pitches, last year’s
          results — and the teams, if it lists them. We build the whole tournament from it; anything missing gets a
          common default, listed on Review.
        </p>
        <FileList files={rulebooks} />
        {!locked && (rulebooks.length > 0 && !moreRules ? (
          <div><button type="button" className="link-btn" onClick={() => setMoreRules(true)}>+ Add another rulebook</button></div>
        ) : (
          <>
            {rulebooks.length > 0 && <p className="hint">Another rulebook is read together with this one.</p>}
            <DocInput input={rulesInput} label="Rulebook" rows={8} placeholder="Paste the rules here" />
          </>
        ))}
      </div>

      {showTeams && (
        <div className="setup-doc">
          <div className="setup-doc-head">
            <h3>Team list</h3>
            {ownLists.length > 0
              ? <span className="pub-status pub-status--done">✓ {teamCount} teams</span>
              : <span className="pub-status pub-status--warn">Required</span>}
          </div>
          <p className="hint">
            {ownLists.length ? '' : 'Your rulebook doesn’t name the teams. Add them here: '}
            a spreadsheet (CSV or Excel), or paste the list — one team per line with the club in brackets, rows copied
            from a spreadsheet, or a WhatsApp message. Contact details are removed.
          </p>
          <FileList files={ownLists} />
          {!locked && (
            <DocInput input={teamsInput} label="Team list" rows={6}
              placeholder={'North Star (North Star SC)\nRiverside United\n… or paste rows from a spreadsheet'} />
          )}
        </div>
      )}

      {!locked && !rulebooks.length && !lists.length && (
        <Templates tournament={setup.tournament} disabled={action.busy} onPick={(text) => rulesInput.set({ mode: 'text', text })} />
      )}

      {setup.status === 'failed' && setup.failure_reason && (
        <p className="form-error" role="alert">Generating the tournament failed: {setup.failure_reason}</p>
      )}
      {action.code === 'processing_agreement_required' ? (
        <div className="notice" role="alert">
          <span>Your organisation hasn’t accepted the data processing terms yet. They’re needed before we read uploaded documents.</span>
          <button className="btn btn--accent btn--sm" disabled={action.busy} onClick={acceptTerms}>Accept the terms and continue</button>
        </div>
      ) : <Notice action={action} />}
      {!locked && (
        <div className="wiz-nav">
          <span className="hint">{hint}</span>
          <button className="btn btn--accent" disabled={!canGenerate || action.busy} onClick={generate}>
            {action.busy ? <><span className="spinner" /> Generating your tournament…</> : extracted && !needTeams ? 'Generate again' : 'Generate my tournament →'}
          </button>
        </div>
      )}
    </section>
  )
}
