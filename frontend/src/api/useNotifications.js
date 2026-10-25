import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './client'

const POLL_MS = 10000

/**
 * Unread notification count for members (polled), plus device notifications:
 * when the fan has allowed them and the tab is in the background, new items pop up as
 * browser notifications. (Push while the app is closed needs a push service — not part of the MVP.)
 */
export function useNotifications(member, onOpen) {
  const [unread, setUnread] = useState(0)
  const lastSeen = useRef(null) // newest notification id already seen
  const openRef = useRef(onOpen)
  useEffect(() => {
    openRef.current = onOpen
  })

  const poll = useCallback(async () => {
    try {
      const page = await api.notifications(undefined, 5)
      setUnread(page.unreadCount)
      const fresh = []
      for (const n of page.items) {
        if (n.id === lastSeen.current) break
        if (!n.read) fresh.push(n)
      }
      const first = lastSeen.current === null
      lastSeen.current = page.items[0]?.id ?? lastSeen.current
      if (!first && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
        for (const n of fresh.reverse()) {
          const note = new Notification(n.title, { body: n.body, tag: n.id })
          note.onclick = () => {
            window.focus()
            openRef.current?.(n)
          }
        }
      }
    } catch {
      /* offline or signed out: try again next time */
    }
  }, [])

  useEffect(() => {
    if (!member) return undefined
    lastSeen.current = null
    const first = setTimeout(poll, 0)
    const id = setInterval(poll, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [member, poll])

  return { unread: member ? unread : 0, refresh: poll }
}
