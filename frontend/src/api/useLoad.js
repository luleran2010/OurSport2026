import { useEffect, useEffectEvent, useState } from 'react'

/** Fetch helper: loads again when `key` changes and ignores stale responses. */
export function useLoad(load, key) {
  const [state, setState] = useState({ key: null, status: 'loading', data: null })
  const run = useEffectEvent(load)
  useEffect(() => {
    let cancelled = false
    run()
      .then((data) => !cancelled && setState({ key, status: 'ready', data }))
      .catch((error) => !cancelled && setState({ key, status: 'error', data: null, error }))
    return () => {
      cancelled = true
    }
  }, [key])
  // While a new key loads, keep showing the previous data (if any).
  return state.key === key ? state : { ...state, status: 'loading' }
}
