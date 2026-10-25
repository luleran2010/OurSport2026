import { useEffect } from 'react'

/** Keep the screen on while scoring (Screen Wake Lock API; silently does nothing where unsupported). */
export function useWakeLock(active) {
  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return
    let lock = null
    let cancelled = false
    const request = async () => {
      try {
        if (document.visibilityState === 'visible') lock = await navigator.wakeLock.request('screen')
        if (cancelled) lock?.release()
      } catch {
        /* battery saver or no permission: the screen may dim */
      }
    }
    const onVisible = () => document.visibilityState === 'visible' && request() // the lock is dropped when the tab hides
    request()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisible)
      lock?.release().catch(() => {})
    }
  }, [active])
}
