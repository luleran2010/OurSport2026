import { useEffect, useState } from 'react'
import { api } from '../api/client'

const POLL_MS = 5000 // GET /matches is cached for 5 s (live pages), so polling faster gains nothing

// Every match of every published tournament (GET /api/v1/matches), polled while the tab is
// visible. The match page adds the live WebSocket on top (useLiveMatch).
export function useLiveFeed() {
  const [state, setState] = useState({ status: 'loading', now: 0, matches: [], posts: [] })

  useEffect(() => {
    let timer
    let stopped = false
    const load = async () => {
      try {
        const feed = await api.liveFeed()
        if (!stopped) setState({ status: 'live', ...feed })
      } catch {
        if (!stopped) setState((s) => ({ ...s, status: s.status === 'loading' || s.status === 'error' ? 'error' : 'reconnecting' }))
      }
      if (!stopped) timer = setTimeout(tick, POLL_MS)
    }
    const tick = () => (document.hidden ? (timer = setTimeout(tick, POLL_MS)) : load())
    const onVisible = () => {
      if (!document.hidden) {
        clearTimeout(timer)
        load()
      }
    }
    load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return state
}
