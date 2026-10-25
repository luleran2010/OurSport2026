import { useEffect } from 'react'
import Sidebar from './fan/Sidebar'
import TopBar from './fan/TopBar'
import NewsFeed from './fan/NewsFeed'
import SignInPrompt from './fan/SignInPrompt'

/**
 * Fan app shell: sidebar (left), page (centre), news feed (right). On phones the sidebar slides in.
 * `navOpen` / `setNavOpen` come from the app so that navigating closes the menu.
 */
export default function FanLayout({
  view, navigate, navOpen, setNavOpen, follow, matches, member, now, notifications, meState, requestLogin,
  followKey, newsVersion, connection, children,
}) {
  // Top-bar search always opens a fresh Explore page for that query.
  const search = (q) => navigate({ type: 'explore', q }, { state: { searchId: Date.now() } })

  useEffect(() => {
    if (!navOpen) return
    const onKey = (e) => e.key === 'Escape' && setNavOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen, setNavOpen])

  return (
    <div className={`shell${navOpen ? ' nav-open' : ''}`}>
      <Sidebar view={view} onNavigate={navigate} followed={follow.followed} followedClubs={follow.clubs}
        followedEvents={follow.tournaments} matches={matches} unread={notifications.unread} />
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <main className="center">
        <TopBar onMenu={() => setNavOpen(true)} onSearch={search} showSearch={view.type !== 'explore'}
          unread={notifications.unread} onBell={() => navigate({ type: 'notifications' })} />
        <div className="center-body">{children}</div>
      </main>
      <NewsFeed member={member} followKey={followKey} version={newsVersion} now={now} onNavigate={navigate} />
      <SignInPrompt
        target={meState.pendingFollow}
        onSignIn={meState.signInAndFollow}
        onGoTo={(mode) => {
          meState.deferPendingFollow()
          requestLogin(mode)
        }}
        onClose={meState.cancelPendingFollow}
      />
      {connection === 'reconnecting' && <div className="conn-banner" role="status">Connection lost — reconnecting…</div>}
    </div>
  )
}
