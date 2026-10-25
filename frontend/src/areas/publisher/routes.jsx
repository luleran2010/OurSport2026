// P1–P5: which publisher page a route shows. The layout is app/layouts/PublisherLayout.
import DashboardView from './DashboardView'
import SetupWizard from './setup/SetupWizard'
import EventManageView from './manage/EventManageView'
import EventContentView from './content/EventContentView'

const COMING = {
  events: { title: 'Events', text: 'Your events, teams, schedules and rules.' },
  news: { title: 'News', text: 'News posts for your events.' },
  'news/new': { title: 'Write news', text: 'Write and publish a news post.' },
  review: { title: 'Review', text: 'Read the AI-written text, fix it and approve or reject it.' },
}

function ComingNext({ view, onNavigate }) {
  const page = COMING[view.sub === 'new' ? `${view.section}/new` : view.section] ?? COMING.events
  return (
    <>
      <div className="page-head">
        <h1>{page.title}</h1>
        <p className="page-sub">{page.text}</p>
      </div>
      <div className="placeholder portal-placeholder">
        <p>This page is coming next.</p>
        <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'publisher' })}>← Dashboard</button>
      </div>
    </>
  )
}

export default function PublisherPage({ view, onNavigate }) {
  if (view.section === 'dashboard') return <DashboardView onNavigate={onNavigate} />
  // Create an event: the backend's automatic setup (upload → review → draw & schedule → publish).
  if (view.section === 'events' && view.sub === 'new') return <SetupWizard key="new" setupId={null} onNavigate={onNavigate} />
  if (view.section === 'events' && (view.page === 'setup' || view.page === 'rules')) {
    return <SetupWizard key={view.sub} setupId={view.sub} onNavigate={onNavigate} />
  }
  if (view.section === 'events' && view.page === 'content') return <EventContentView key={view.sub} eventId={view.sub} onNavigate={onNavigate} />
  if (view.section === 'events' && view.sub && !view.page) return <EventManageView key={view.sub} eventId={view.sub} onNavigate={onNavigate} />
  return <ComingNext view={view} onNavigate={onNavigate} />
}
