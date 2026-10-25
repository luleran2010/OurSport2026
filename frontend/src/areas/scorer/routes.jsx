// S1–S2: which scorer page a route shows. The layout is app/layouts/ScorerLayout.
import MyMatchesView from './MyMatchesView'
import ConsoleView from './ConsoleView'

export default function ScorerPage({ view, onNavigate }) {
  if (view.matchId) return <ConsoleView key={view.matchId} matchId={view.matchId} onNavigate={onNavigate} />
  return <MyMatchesView onNavigate={onNavigate} />
}
