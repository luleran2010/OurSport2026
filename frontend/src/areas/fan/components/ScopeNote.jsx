/** "Showing what you follow · Manage" line for members on browsing pages. */
export default function ScopeNote({ member, onNavigate }) {
  if (!member) return null
  return (
    <>
      {' · '}Showing what you follow ·{' '}
      <button className="link-btn link-btn--accent" onClick={() => onNavigate({ type: 'following' })}>Manage</button>
    </>
  )
}
