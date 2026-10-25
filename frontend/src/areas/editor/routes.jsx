// E1–E3: which editor desk page a route shows. The layout is app/layouts/EditorLayout.
import QueueView from './QueueView'
import ReviewItemView from './ReviewItemView'
import PublishedView from './PublishedView'

export default function EditorPage({ view, onNavigate }) {
  // keyed by item: J/K to the next item starts with a clean page (no half-typed reject reason carried over)
  if (view.itemId) return <ReviewItemView key={view.itemId} itemId={view.itemId} onNavigate={onNavigate} />
  if (view.section === 'published') return <PublishedView onNavigate={onNavigate} />
  return <QueueView onNavigate={onNavigate} />
}
