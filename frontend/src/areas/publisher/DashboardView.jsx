import { useState } from 'react'
import Loading from '../../components/Loading'
import { useCatalog } from '../../app/providers/catalog'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import { formatDateRange, timeAgo } from '../../utils/time'
import { RemoveEvent, StatusPill } from './setup/shared'

// P1: my events — setups in progress and published tournaments (GET /setup).

const NEXT = {
  intake: 'Upload the team list and the rulebook.',
  extracting: 'Reading the documents…',
  failed: 'Reading the documents failed: check the files and try again.',
  needs_answers: 'Answer a few questions so the draw and schedule can be made.',
  drawing: 'Drawing groups and planning the schedule…',
  ready: 'Check the draw and the schedule, then publish.',
  published: 'Live for fans. Print the scorer passes for the pitches.',
}

function EventCard({ s, now, onNavigate, onRemoved }) {
  const { sportIcon, sportLabel } = useCatalog()
  const t = s.tournament
  const published = s.status === 'published'
  const open = () => onNavigate({ type: 'publisher', section: 'events', sub: s.id, page: 'setup' })
  return (
    <li className={`pub-event pub-event--${published ? 'scheduled' : s.status === 'needs_answers' ? 'rules_pending' : 'draft'}`}>
      <div className="pub-event-head">
        <StatusPill status={s.status} />
        <span className="pub-sport">{sportIcon(t.sport)} {sportLabel(t.sport)}{t.is_junior ? ` · ${t.age_group.toUpperCase()}` : ''}</span>
      </div>
      <h3>{t.name}</h3>
      <p className="pub-when">
        {t.starts_on ? formatDateRange(Date.parse(t.starts_on), Date.parse(t.ends_on ?? t.starts_on)) : 'Dates not set'}
        {' · '}changed {timeAgo(Date.parse(s.updated_at), now)}
      </p>
      <p className="pub-next"><strong>Next:</strong> {NEXT[s.status] ?? ''}</p>
      <div className="pub-actions">
        <button className="btn btn--ghost btn--sm" onClick={open}>{published ? 'Setup & scorer passes' : 'Continue setup'}</button>
        {published && (
          <button className="link-btn" onClick={() => onNavigate({ type: 'event', eventId: s.tournament_id })}>Fan page ↗</button>
        )}
        <RemoveEvent setup={s} onRemoved={onRemoved} />
      </div>
    </li>
  )
}

export default function DashboardView({ onNavigate }) {
  const { me } = useMeContext()
  const [removed, setRemoved] = useState(0)
  const state = useLoad(() => api.listSetups(), `setups:${me?.id ?? ''}:${removed}`)
  const [now] = useState(() => Date.now())
  const first = (me?.name ?? '').split(' ')[0]
  const create = () => onNavigate({ type: 'publisher', section: 'events', sub: 'new' })
  return (
    <>
      <div className="page-head page-head--row">
        <div>
          <h1>My events</h1>
          <p className="page-sub">{first ? `Hi ${first}. ` : ''}Upload your rules and team list — we set up the rest.</p>
        </div>
        <div className="pub-quick">
          <button className="btn btn--accent" onClick={create}>+ Create event</button>
        </div>
      </div>
      <Loading state={state} empty="">
        {(setups) => {
          const drafts = setups.filter((s) => s.status !== 'published')
          const live = setups.filter((s) => s.status === 'published')
          if (!setups.length) {
            return (
              <div className="placeholder">
                <p>No events yet.</p>
                <button className="btn btn--accent" onClick={create}>Create your first event</button>
              </div>
            )
          }
          return (
            <>
              {drafts.length > 0 && (
                <section className="section" aria-labelledby="drafts-h">
                  <div className="section-head"><h2 id="drafts-h">In setup</h2></div>
                  <ul className="pub-events">{drafts.map((s) => <EventCard key={s.id} s={s} now={now} onNavigate={onNavigate} onRemoved={() => setRemoved((n) => n + 1)} />)}</ul>
                </section>
              )}
              {live.length > 0 && (
                <section className="section" aria-labelledby="live-h">
                  <div className="section-head"><h2 id="live-h">Published</h2></div>
                  <ul className="pub-events">{live.map((s) => <EventCard key={s.id} s={s} now={now} onNavigate={onNavigate} />)}</ul>
                </section>
              )}
            </>
          )
        }}
      </Loading>
    </>
  )
}
