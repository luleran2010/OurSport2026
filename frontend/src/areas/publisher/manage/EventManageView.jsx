import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../../../api/client'
import { useLoad } from '../../../api/useLoad'
import { useCatalog } from '../../../app/providers/catalog'
import { formatDateRange } from '../../../utils/time'
import OverviewTab from './OverviewTab'
import FixturesTab from './FixturesTab'
import TeamsTab from './TeamsTab'
import ScorersTab from './ScorersTab'
import SettingsTab from './SettingsTab'

const TABS = [
  ['overview', 'Overview'], ['fixtures', 'Fixtures and results'], ['teams', 'Teams'], ['scorers', 'Scorers'], ['settings', 'Settings'],
]
const STATUS = { scheduled: ['Scheduled', 'info'], live: ['Live', 'live'], finished: ['Finished', 'done'] }
const POLL_MS = 20_000

/** Not published yet: where the event is in its setup, and the way back into the wizard / rules review. */
function NotPublished({ d, eventId, onNavigate }) {
  const next = d.status === 'draft' ? 'setup' : d.status === 'rules_pending' ? 'rules' : null
  return (
    <>
      <div className="page-head">
        <button className="link-btn" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
        <h1>{d.name}</h1>
        <p className="page-sub">This event isn’t published yet, so there are no matches to manage.</p>
      </div>
      <div className="ev-card ev-unpublished">
        <p><b>Status:</b> {d.status === 'draft' ? 'Draft' : d.status === 'rules_pending' ? 'Rules to check' : d.status === 'scheduled' ? 'Rules confirmed' : 'Finished'}</p>
        <p className="page-sub">
          {d.teams.length} teams · {d.fixtures.length} fixtures{d.startDate ? ` · ${d.startDate} – ${d.endDate}` : ''}
        </p>
        {next && (
          <button className="btn btn--accent" onClick={() => onNavigate({ type: 'publisher', section: 'events', sub: eventId, page: next })}>
            {next === 'setup' ? 'Continue setup' : 'Review rules'}
          </button>
        )}
        {d.status === 'scheduled' && (
          <p className="page-sub">The rules are confirmed. Publishing an event from its setup isn’t in the portal yet — OurSport publishes it for you.</p>
        )}
      </div>
    </>
  )
}

/** P4 Event management: overview, fixtures and results, teams, scorers, settings. */
export default function EventManageView({ eventId, onNavigate }) {
  const { sportIcon, sportLabel } = useCatalog()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(([id]) => id === params.get('tab')) ? params.get('tab') : 'overview'
  const [kick, setKick] = useState(0)
  const state = useLoad(() => api.eventSetup(eventId), `${eventId}#${kick}`)
  const d = state.data
  const reload = () => setKick((k) => k + 1)

  // live scores and statuses: look again every 20 s while the tab is visible
  useEffect(() => {
    const id = setInterval(() => document.visibilityState === 'visible' && setKick((k) => k + 1), POLL_MS)
    return () => clearInterval(id)
  }, [])

  const setTab = (t, extra = {}) => setParams({ tab: t, ...extra }, { replace: true })

  if (!d) {
    if (state.status === 'error') {
      return (
        <div className="placeholder portal-placeholder">
          <p>{state.error?.status === 404 ? 'Event not found.' : state.error?.message}</p>
          <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
        </div>
      )
    }
    return <p className="page-sub" aria-busy="true"><span className="spinner" /> Loading the event…</p>
  }
  if (d.kind !== 'managed') return <NotPublished d={d} eventId={eventId} onNavigate={onNavigate} />

  const [label, tone] = STATUS[d.status]
  const shared = { d, eventId, reload, onNavigate, setTab }
  return (
    <div className="ev">
      <div className="page-head page-head--row">
        <div>
          <button className="link-btn" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
          <h1>{d.name}</h1>
          <p className="page-sub">
            <span className={`pub-status pub-status--${tone}`}>{label}</span>{' '}
            {sportIcon(d.sport)} {sportLabel(d.sport)} · {formatDateRange(d.startsAt, d.endsAt)} · {d.venue}
            {d.junior && <span className="ev-tag" title="Junior protection: no player data for fans">Junior</span>}
            {d.settings.visibility !== 'public' && <span className="ev-tag ev-tag--warn">{d.settings.visibility === 'hidden' ? 'Hidden from fans' : 'Unlisted'}</span>}
          </p>
        </div>
        <div className="ev-head-actions">
          <button className="btn btn--accent btn--sm" onClick={() => onNavigate({ type: 'publisher', section: 'events', sub: eventId, page: 'content' })}>
            ✎ News and content
          </button>
          <button className="btn btn--ghost btn--sm" onClick={() => onNavigate({ type: 'event', eventId: d.tournamentId })}>Fan page ↗</button>
        </div>
      </div>

      <div className="ev-tabs" role="tablist" aria-label="Event sections">
        {TABS.map(([id, text]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'is-active' : ''} onClick={() => setTab(id)}>
            {text}
            {id === 'fixtures' && d.counts.awaiting_result > 0 && <span className="ev-badge">{d.counts.awaiting_result}</span>}
            {id === 'scorers' && <span className="ev-badge ev-badge--soft">{d.scorers.length}</span>}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === 'overview' && <OverviewTab {...shared} />}
        {tab === 'fixtures' && <FixturesTab {...shared} filter={params.get('show') ?? 'all'} />}
        {tab === 'teams' && <TeamsTab {...shared} />}
        {tab === 'scorers' && <ScorersTab {...shared} />}
        {tab === 'settings' && <SettingsTab {...shared} />}
      </div>
    </div>
  )
}
