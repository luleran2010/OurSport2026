// F1–F13: which fan page a route shows. The shell around it is app/layouts/FanLayout.
import HomeView from './HomeView'
import LiveView from './LiveView'
import MatchesView from './MatchesView'
import TeamView from './TeamView'
import ManageTeamsView from './ManageTeamsView'
import AccountView from './AccountView'
import ExploreView from './ExploreView'
import ClubView from './ClubView'
import StoryView from './StoryView'
import MatchView from './MatchView'
import EventView from './EventView'
import EventsView from './EventsView'
import AccountPage from './AccountPage'
import PlayerView from './PlayerView'
import FollowingView from './FollowingView'
import NotificationsView from './NotificationsView'
import AuthView from './AuthView'
import LegalView from './LegalView'
import InviteView from './InviteView'

/**
 * `shared`: live data for any page ({ matches, posts, now, followed, onNavigate }).
 * `scoped`: the same, but members only see games of what they follow (home, live, schedule, results).
 */
export default function FanPage({ view, shared, scoped, follow, notifications, searchId }) {
  const { now, onNavigate } = shared
  switch (view.type) {
    case 'live':
      return <LiveView {...scoped} />
    case 'schedule':
    case 'results':
      return <MatchesView kind={view.type} {...scoped} />
    case 'team':
      return <TeamView key={view.teamId} teamId={view.teamId} follow={follow} {...shared} />
    case 'teams':
      return <ManageTeamsView follow={follow} onNavigate={onNavigate} />
    case 'explore':
      return <ExploreView key={searchId ?? 'explore'} follow={follow} {...shared} />
    case 'club':
      return <ClubView key={view.clubId} clubId={view.clubId} follow={follow} {...shared} />
    case 'following':
      return <FollowingView follow={follow} {...shared} />
    case 'player':
      return <PlayerView key={view.playerId} playerId={view.playerId} {...shared} />
    case 'account':
    case 'premium': // old link target; F10 lives at /me/account
      return <AccountPage {...shared} />
    case 'events':
      return <EventsView {...shared} />
    case 'event':
      return <EventView key={view.eventId} eventId={view.eventId} follow={follow} {...shared} />
    case 'story':
      return <StoryView key={view.storyId} storyId={view.storyId} {...shared} />
    case 'match':
      return <MatchView key={view.matchId} matchId={view.matchId} {...shared} />
    case 'login':
    case 'signup':
    case 'verify':
      return <AuthView key={view.type} mode={view.type} onNavigate={onNavigate} />
    case 'invite':
      return <InviteView key={view.token} token={view.token} onNavigate={onNavigate} />
    case 'terms':
    case 'privacy':
      return <LegalView kind={view.type} />
    case 'notifications':
      return <NotificationsView notifications={notifications} now={now} onNavigate={onNavigate} />
    case 'profile':
    case 'settings':
      return <AccountView kind={view.type} />
    case 'notfound':
      return (
        <div className="page-head">
          <h1>Page not found</h1>
          <p className="page-sub">
            That address doesn’t exist.{' '}
            <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'home' })}>Go to the home feed</button>
          </p>
        </div>
      )
    default:
      return <HomeView {...scoped} />
  }
}
