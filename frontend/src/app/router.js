// URL <-> view mapping. Views are plain objects like { type: 'team', teamId }.

const SIMPLE = new Set(['terms', 'privacy', 'live', 'schedule', 'results', 'teams', 'explore', 'events', 'premium', 'profile', 'notifications', 'settings'])

export function pathFor(view) {
  switch (view.type) {
    case 'home':
      return '/'
    case 'team':
      return `/teams/${encodeURIComponent(view.teamId)}`
    case 'club':
      return `/clubs/${encodeURIComponent(view.clubId)}${view.tab ? `?tab=${view.tab}` : ''}`
    case 'event':
      return `/events/${encodeURIComponent(view.eventId)}${view.tab ? `?tab=${view.tab}` : ''}`
    case 'login':
    case 'signup':
    case 'verify': {
      const q = new URLSearchParams()
      if (view.next) q.set('next', view.next)
      if (view.token) q.set('token', view.token)
      const qs = q.toString()
      return `/auth/${view.type}${qs ? `?${qs}` : ''}`
    }
    case 'publisher':
      return `/publisher${view.section && view.section !== 'dashboard' ? `/${view.section}` : ''}${view.sub ? `/${encodeURIComponent(view.sub)}` : ''}${view.page ? `/${view.page}` : ''}`
    case 'editor':
      return view.itemId ? `/editor/items/${encodeURIComponent(view.itemId)}` : view.section === 'published' ? '/editor/published' : '/editor'
    case 'scorer':
      return view.matchId ? `/score/${encodeURIComponent(view.matchId)}` : '/score'
    case 'invite':
      return `/invite/${encodeURIComponent(view.token)}`
    case 'following':
      return '/me/following'
    case 'account':
      return '/me/account'
    case 'notifications':
      return '/me/notifications'
    case 'player':
      return `/players/${encodeURIComponent(view.playerId)}`
    case 'story':
      return `/stories/${encodeURIComponent(view.storyId)}`
    case 'match':
      return `/matches/${encodeURIComponent(view.matchId)}`
    case 'explore':
      return view.q ? `/explore?q=${encodeURIComponent(view.q)}` : '/explore'
    default:
      return `/${view.type}`
  }
}

export function viewFromPath(pathname) {
  let parts
  try {
    parts = pathname.split('/').filter(Boolean).map(decodeURIComponent)
  } catch {
    return { type: 'notfound' }
  }
  const [a, b, ...rest] = parts
  if (!a) return { type: 'home' }
  // Publisher portal: /publisher, /publisher/{events|news|review}[/{id|new}]
  if (a === 'publisher' && rest.length <= 1 && (!b || ['events', 'news', 'review'].includes(b))) {
    return { type: 'publisher', section: b ?? 'dashboard', sub: rest[0] }
  }
  // ... /publisher/events/{id}/setup (P2 wizard), /rules (P3), /content (P5); /publisher/events/{id} is P4
  if (a === 'publisher' && b === 'events' && rest.length === 2 && ['setup', 'rules', 'content'].includes(rest[1])) {
    return { type: 'publisher', section: 'events', sub: rest[0], page: rest[1] }
  }
  // Editor desk: /editor (E1 review queue), /editor/items/{itemId} (E2 review item)
  if (a === 'editor' && !b) return { type: 'editor' }
  if (a === 'editor' && b === 'published' && !rest.length) return { type: 'editor', section: 'published' }  // E3
  if (a === 'editor' && b === 'items' && rest.length === 1) return { type: 'editor', itemId: rest[0] }
  // Scorer area: /score (S1 my matches), /score/{matchId} (S2 scoring console)
  if (a === 'score' && !rest.length) return { type: 'scorer', matchId: b }
  if (rest.length) return { type: 'notfound' }
  if (a === 'teams' && b) return { type: 'team', teamId: b }
  if (a === 'clubs' && b) return { type: 'club', clubId: b }
  if (a === 'events' && b) return { type: 'event', eventId: b }
  if (a === 'auth' && ['login', 'signup', 'verify'].includes(b)) return { type: b }
  if (a === 'invite' && b) return { type: 'invite', token: b }
  if (a === 'me' && b === 'following') return { type: 'following' }
  if (a === 'me' && b === 'account') return { type: 'account' }
  if (a === 'me' && b === 'notifications') return { type: 'notifications' }
  if (a === 'players' && b) return { type: 'player', playerId: b }
  if (a === 'stories' && b) return { type: 'story', storyId: b }
  if (a === 'matches' && b) return { type: 'match', matchId: b }
  if (!b && SIMPLE.has(a)) return { type: a }
  return { type: 'notfound' }
}

/** Only same-app paths are allowed as a post-login redirect (no open redirects, no auth loops). */
export function safeNext(next) {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/auth/')) return '/'
  return next
}
