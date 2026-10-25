import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import StartStep from './StartStep'
import DocumentsStep from './DocumentsStep'
import ReviewStep from './ReviewStep'
import DrawStep from './DrawStep'
import PublishStep from './PublishStep'
import { RemoveEvent, StatusPill } from './shared'

// Create an event with the backend's automatic setup: the organiser uploads the team list and
// rules, the AI drafts the tournament, the engine draws and schedules it, the organiser publishes.

const STEPS = [
  { n: 1, label: 'Basics' },
  { n: 2, label: 'Documents' },
  { n: 3, label: 'Review' },
  { n: 4, label: 'Draw & schedule' },
  { n: 5, label: 'Publish' },
]

/** The furthest step a setup in this status can open. */
function reachable(setup) {
  if (!setup) return 1
  return { intake: 2, extracting: 2, failed: 2, needs_answers: 3, drawing: 3, ready: 5, published: 5 }[setup.status] ?? 2
}

/** Where to land when a setup opens (back on Documents while the rulebook named no teams). */
function landing(setup) {
  if (!setup) return 1
  if (setup.draft?.open_questions.some((q) => q.field === 'teams')) return 2
  return { intake: 2, extracting: 2, failed: 2, needs_answers: 3, drawing: 3, ready: 4, published: 5 }[setup.status] ?? 2
}

function Progress({ step, top, onPick }) {
  return (
    <ol className="wiz-progress wiz-progress--5" aria-label="Steps">
      {STEPS.map((s) => {
        const state = s.n === step ? 'current' : s.n < top || (s.n === top && s.n < step) ? 'done' : 'todo'
        return (
          <li key={s.n} className={`wiz-step wiz-step--${state}`} aria-current={s.n === step ? 'step' : undefined}>
            <button disabled={s.n > top || s.n === step} onClick={() => onPick(s.n)}>
              <span className="wiz-num">{state === 'done' ? '✓' : s.n}</span>
              <span>{s.label}</span>
            </button>
          </li>
        )
      })}
      <li className="wiz-bar" aria-hidden="true"><span style={{ width: `${((top - 1) / 4) * 100}%` }} /></li>
    </ol>
  )
}

/** setupId = null: a new event (step 1); otherwise the setup to continue. */
export default function SetupWizard({ setupId, onNavigate }) {
  const [setup, setSetup] = useState(null)
  const [load, setLoad] = useState({ status: setupId ? 'loading' : 'ready', error: null })
  const [step, setStep] = useState(setupId ? null : 1)

  const reload = async () => {
    const next = await api.getSetup(setupId)
    setSetup(next)
    return next
  }

  useEffect(() => {
    if (!setupId) return undefined
    let cancelled = false
    api.getSetup(setupId)
      .then((s) => {
        if (cancelled) return
        setSetup(s)
        setStep((current) => current ?? landing(s))
        setLoad({ status: 'ready', error: null })
      })
      .catch((error) => !cancelled && setLoad({ status: 'error', error }))
    return () => {
      cancelled = true
    }
  }, [setupId])

  /** A step changed the setup: keep it, and move on when the status opens the next step. */
  const changed = (next, goTo) => {
    setSetup(next)
    if (goTo) setStep(goTo)
  }

  if (load.status === 'error') {
    return (
      <div className="wizard">
        <p className="empty">{load.error?.status === 404 ? 'This setup doesn’t exist, or isn’t yours.' : 'Couldn’t load the setup right now.'}</p>
        <button className="link-btn" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
      </div>
    )
  }
  if (load.status === 'loading' || !step) return <p className="page-sub" aria-busy="true"><span className="spinner" /> Loading the setup…</p>

  const top = reachable(setup)
  const shared = { setup, reload, onChange: changed, onNavigate }
  return (
    <div className="wizard">
      <div className="page-head">
        <button className="link-btn back-link" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
        <h1>{setup?.tournament?.name ?? 'Create event'}</h1>
        <p className="page-sub">
          {setup ? <StatusPill status={setup.status} /> : 'Upload your team list and rules — we set up groups, seeding and the schedule.'}
          {setup && setup.status !== 'published' && ' · saved as you go; you can come back any time'}
        </p>
        {setup && <RemoveEvent setup={setup} onRemoved={() => onNavigate({ type: 'publisher' })} />}
      </div>
      <Progress step={step} top={top} onPick={setStep} />
      {step === 1 && (
        <StartStep setup={setup} onStarted={(s) => {
          onNavigate({ type: 'publisher', section: 'events', sub: s.id, page: 'setup' }, { replace: true })
          changed(s, 2)
        }} onNext={() => setStep(2)} />
      )}
      {step === 2 && setup && <DocumentsStep {...shared} onDone={(s) => changed(s, landing(s))} />}
      {step === 3 && setup && <ReviewStep {...shared} onNext={() => setStep(4)} />}
      {step === 4 && setup && <DrawStep {...shared} onBack={() => setStep(3)} onNext={() => setStep(5)} />}
      {step === 5 && setup && <PublishStep {...shared} onBack={() => setStep(4)} />}
    </div>
  )
}
