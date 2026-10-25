/** For members who follow nothing yet: browsing pages only show what they follow. */
export default function FollowSomethingPrompt({ onNavigate }) {
  return (
    <div className="premium-lock home-empty">
      <span className="lock-icon" aria-hidden="true">⭐</span>
      <div>
        <h2>Make this feed yours</h2>
        <p>Live games, fixtures and results are shown only for the clubs, teams and events you follow.</p>
        <div className="lock-actions">
          <button className="btn btn--accent btn--sm" onClick={() => onNavigate({ type: 'explore' })}>Find clubs &amp; teams</button>
          <button className="btn btn--ghost btn--sm" onClick={() => onNavigate({ type: 'events' })}>Browse events</button>
        </div>
      </div>
    </div>
  )
}
