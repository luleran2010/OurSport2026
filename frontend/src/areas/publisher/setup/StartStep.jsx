import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { formatDateRange } from '../../../utils/time'
import { Notice } from './shared'
import { useAction } from './setup'

const AGE_GROUPS = ['adult', 'u19', 'u18', 'u17', 'u16', 'u15', 'u14', 'u13', 'u12', 'u11', 'u10', 'u9']
const KINDS = [
  { id: 'club', label: 'Club' }, { id: 'association', label: 'Association' },
  { id: 'school', label: 'School' }, { id: 'community', label: 'Community' },
]
const LANGUAGES = [{ id: 'en', label: 'English' }, { id: 'fi', label: 'Suomi' }, { id: 'bn', label: 'বাংলা' }]
const NEW = '__new__'

const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Helsinki'
const ageLabel = (a) => (a === 'adult' ? 'Adults' : a.toUpperCase())

/** Step 1: who organises it and the basics. Once started, the basics are fixed (shown read-only). */
export default function StartStep({ setup, onStarted, onNext }) {
  if (setup) {
    const t = setup.tournament
    return (
      <section className="profile-card wiz-card">
        <h2>Basics</h2>
        <dl className="setup-facts">
          <div><dt>Event</dt><dd>{t.name}</dd></div>
          <div><dt>Sport</dt><dd>{t.sport === 'futsal' ? 'Futsal' : 'Football'} · {ageLabel(t.age_group)}{t.is_junior ? ' (junior)' : ''}</dd></div>
          <div><dt>Dates</dt><dd>{t.starts_on ? formatDateRange(Date.parse(t.starts_on), Date.parse(t.ends_on ?? t.starts_on)) : 'Not set'}</dd></div>
          <div><dt>Time zone</dt><dd>{t.time_zone}</dd></div>
        </dl>
        <p className="hint">These were fixed when the setup started. To change them, start a new event.</p>
        <div className="wiz-nav"><span /><button className="btn btn--accent" onClick={onNext}>Next: documents →</button></div>
      </section>
    )
  }
  return <StartForm onStarted={onStarted} />
}

function StartForm({ onStarted }) {
  const [orgs, setOrgs] = useState(null)
  const [f, setF] = useState({
    organisation: '', orgName: '', orgKind: 'club', orgTown: '', terms: false,
    name: '', sport: 'football', ageGroup: 'adult', startsOn: '', endsOn: '', timeZone: browserZone(), language: 'en',
  })
  const action = useAction(() => {}, async () => {})
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))

  useEffect(() => {
    api.myOrganisations()
      .then((list) => {
        setOrgs(list)
        setF((x) => ({ ...x, organisation: list[0]?.id ?? NEW }))
      })
      .catch(() => {
        setOrgs([])
        setF((x) => ({ ...x, organisation: NEW }))
      })
  }, [])

  const creating = f.organisation === NEW
  const invalid = !f.name.trim() || (creating && (!f.orgName.trim() || !f.terms)) || (f.endsOn && f.startsOn && f.endsOn < f.startsOn)

  const submit = (e) => {
    e.preventDefault()
    action.run(async () => {
      let organisationId = f.organisation
      if (creating) {
        const sports = [f.sport]
        const org = await api.createOrganisation({ kind: f.orgKind, name: f.orgName.trim(), town: f.orgTown.trim() || null, sports })
        organisationId = org.id
        // keep it selected, so a retry after a failed start doesn't create it twice
        setOrgs((list) => [...list, { id: org.id, name: org.name }])
        set('organisation', org.id)
      }
      const setup = await api.startSetup({
        organisation_id: organisationId, name: f.name.trim(), sport: f.sport, age_group: f.ageGroup, time_zone: f.timeZone,
        starts_on: f.startsOn || null, ends_on: f.endsOn || f.startsOn || null, organiser_language: f.language,
      })
      onStarted(setup)
      return null
    })
  }

  if (!orgs) return <p className="page-sub" aria-busy="true"><span className="spinner" /> Loading your organisations…</p>
  return (
    <form className="profile-card wiz-card" onSubmit={submit}>
      <h2>Who organises it?</h2>
      <label className="field">
        <span>Organisation</span>
        <select value={f.organisation} onChange={(e) => set('organisation', e.target.value)}>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          <option value={NEW}>+ A new organisation…</option>
        </select>
      </label>
      {creating && (
        <fieldset className="field setup-new-org">
          <legend>New organisation</legend>
          <div className="field-row">
            <label className="field"><span>Name</span>
              <input required maxLength={120} value={f.orgName} onChange={(e) => set('orgName', e.target.value)} placeholder="FinBangla SC" />
            </label>
            <label className="field"><span>Kind</span>
              <select value={f.orgKind} onChange={(e) => set('orgKind', e.target.value)}>
                {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
            </label>
          </div>
          <label className="field"><span>Town (optional)</span>
            <input maxLength={80} value={f.orgTown} onChange={(e) => set('orgTown', e.target.value)} />
          </label>
          <label className="consent">
            <input type="checkbox" checked={f.terms} onChange={(e) => set('terms', e.target.checked)} />
            <span>
              We accept the <a href="/privacy" target="_blank" rel="noreferrer">data processing terms</a>: our organisation
              is responsible for the participant data we upload; OurSport processes it for us.
            </span>
          </label>
        </fieldset>
      )}

      <h2>The event</h2>
      <label className="field"><span>Event name</span>
        <input required maxLength={120} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="FinBangla Cup 2026" />
      </label>
      <div className="field-row">
        <label className="field"><span>Sport</span>
          <select value={f.sport} onChange={(e) => set('sport', e.target.value)}>
            <option value="football">Football</option>
            <option value="futsal">Futsal</option>
          </select>
        </label>
        <label className="field"><span>Age group</span>
          <select value={f.ageGroup} onChange={(e) => set('ageGroup', e.target.value)}>
            {AGE_GROUPS.map((a) => <option key={a} value={a}>{ageLabel(a)}</option>)}
          </select>
        </label>
      </div>
      <div className="field-row">
        <label className="field"><span>First day</span>
          <input type="date" value={f.startsOn} onChange={(e) => set('startsOn', e.target.value)} />
        </label>
        <label className="field"><span>Last day</span>
          <input type="date" value={f.endsOn} min={f.startsOn || undefined} onChange={(e) => set('endsOn', e.target.value)} />
        </label>
      </div>
      <div className="field-row">
        <label className="field"><span>Time zone</span>
          <input value={f.timeZone} onChange={(e) => set('timeZone', e.target.value)} />
        </label>
        <label className="field"><span>Language of your documents</span>
          <select value={f.language} onChange={(e) => set('language', e.target.value)}>
            {LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </label>
      </div>
      {f.ageGroup !== 'adult' && (
        <p className="hint">🛡 Junior event: players are hidden until a guardian consents, and no percentages are shown.</p>
      )}
      <Notice action={action} />
      <div className="wiz-nav">
        <span className="hint">Dates help us plan the schedule; you can also give them in the rulebook.</span>
        <button className="btn btn--accent" disabled={invalid || action.busy}>{action.busy ? 'Starting…' : 'Start setup →'}</button>
      </div>
    </form>
  )
}
