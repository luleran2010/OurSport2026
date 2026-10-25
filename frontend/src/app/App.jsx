import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { pathFor, viewFromPath } from './router'
import AppProviders from './AppProviders'
import RoleGuard from './RoleGuard'
import FanLayout from './layouts/FanLayout'
import ScorerLayout from './layouts/ScorerLayout'
import ScorerPage from '../areas/scorer/routes'
import PublisherLayout from './layouts/PublisherLayout'
import PublisherPage from '../areas/publisher/routes'
import EditorLayout from './layouts/EditorLayout'
import EditorPage from '../areas/editor/routes'
import FanPage from '../areas/fan/routes'
import { useCatalogData } from '../api/useCatalogData'
import { useMe } from '../api/useMe'
import { useNotifications } from '../api/useNotifications'
import { useLiveFeed } from '../live/useLiveFeed'
import '../styles/app.css'

/** Areas: fan (F1–F13), scorer (S1–S2), publisher (P1–P5), editor desk (E1–E3). */
export default function App() {
  const catalog = useCatalogData()
  const { matches, posts, now, status } = useLiveFeed()
  const meState = useMe()
  const { follow } = meState
  const location = useLocation()
  const routerNavigate = useNavigate()
  const view = viewFromPath(location.pathname)
  const [navOpen, setNavOpen] = useState(false)

  const navigate = (v, options) => {
    routerNavigate(pathFor(v), options)
    setNavOpen(false)
    window.scrollTo({ top: 0 })
  }

  const notifications = useNotifications(Boolean(meState.me?.signedIn), (n) => {
    if (n.link?.type === 'match') navigate({ type: 'match', matchId: n.link.id })
    else if (n.link?.type === 'story') navigate({ type: 'story', storyId: n.link.id })
    else navigate({ type: 'notifications' })
  })

  // Members-only buttons send visitors to log in and come back here afterwards (F12).
  const requestLogin = (mode = 'login') => {
    const here = `${location.pathname}${location.search}`
    navigate({ type: mode, next: here.startsWith('/auth/') ? undefined : here })
  }

  // The scorer pages work offline (saved account, catalog and assignments), so they don't wait for the live feed.
  const needsFeed = view.type !== 'scorer'
  if (catalog.status === 'error' || meState.status === 'error' || (needsFeed && status === 'error' && catalog.status !== 'loading')) {
    return (
      <div className="splash">
        <h1>Can’t reach the OurSport AI server</h1>
        <p>Start the backend and reload this page:</p>
        <pre>cd backend{'\n'}uv sync{'\n'}uv run uvicorn app.main:app --reload --port 8000</pre>
        <button className="btn btn--accent" onClick={() => window.location.reload()}>Reload</button>
      </div>
    )
  }
  if (catalog.status === 'loading' || meState.status === 'loading' || (needsFeed && status === 'loading')) {
    return <div className="splash" aria-busy="true"><span className="spinner" />Loading live sport…</div>
  }

  let area
  if (view.type === 'editor') {
    area = (
      <RoleGuard role="editor" onNavigate={navigate}>
        {() => (
          <EditorLayout section={view.itemId ? null : view.section ?? 'queue'} onNavigate={navigate}>
            <EditorPage view={view} onNavigate={navigate} />
          </EditorLayout>
        )}
      </RoleGuard>
    )
  } else if (view.type === 'publisher') {
    area = (
      <RoleGuard role="publisher" onNavigate={navigate}>
        {() => (
          <PublisherLayout section={view.section} onNavigate={navigate}>
            <PublisherPage view={view} onNavigate={navigate} />
          </PublisherLayout>
        )}
      </RoleGuard>
    )
  } else if (view.type === 'scorer') {
    area = (
      // The server checks access to the requested match.
      <RoleGuard role="scorer" onNavigate={navigate}>
        {() => (
          <ScorerLayout onNavigate={navigate}>
            <ScorerPage view={view} onNavigate={navigate} />
          </ScorerLayout>
        )}
      </RoleGuard>
    )
  } else {
    // Teams the fan follows directly or through a followed club (for highlights and "My teams").
    const followedAll = [
      ...new Set([...follow.followed, ...follow.clubs.flatMap((id) => catalog.clubs[id]?.teamIds ?? [])]),
    ]
    const member = Boolean(meState.me?.signedIn)
    const shared = { matches, posts, now, followed: followedAll, onNavigate: navigate }
    // Browsing pages (home, live, schedule, results): members only see games of what they follow.
    const followedSet = new Set(followedAll)
    const myMatches = member
      ? matches.filter(
          (m) => followedSet.has(m.home.id) || followedSet.has(m.away.id) || follow.tournaments.includes(m.tournamentId),
        )
      : matches
    const followsNothing = member && followedAll.length === 0 && follow.tournaments.length === 0
    const scoped = { ...shared, matches: myMatches, member, followsNothing }
    area = (
      <FanLayout
        view={view} navigate={navigate} navOpen={navOpen} setNavOpen={setNavOpen} follow={follow} matches={myMatches}
        member={member} now={now} notifications={notifications} meState={meState} requestLogin={requestLogin}
        // The news column restarts from the top when follows change or a game finishes (new report).
        followKey={JSON.stringify(meState.me?.follows ?? {})}
        newsVersion={matches.filter((m) => m.status === 'finished').length}
        connection={status}
      >
        <FanPage view={view} shared={shared} scoped={scoped} follow={follow} notifications={notifications}
          searchId={location.state?.searchId} />
      </FanLayout>
    )
  }

  return (
    <AppProviders catalog={catalog} meState={meState} requestLogin={requestLogin}>
      {area}
    </AppProviders>
  )
}
