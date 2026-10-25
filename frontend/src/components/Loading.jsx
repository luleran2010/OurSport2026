/** Renders loading / error states around data from useLoad. */
export default function Loading({ state, children, empty }) {
  if (state.status === 'error') return <p className="empty">Couldn’t load this right now.</p>
  if (!state.data) return <p className="page-sub">Loading…</p>
  return children(state.data) ?? <p className="empty">{empty}</p>
}
