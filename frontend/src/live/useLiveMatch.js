import { useEffect, useState } from 'react'
import { api } from '../api/client'

/**
 * Live updates for one match over the v1 WebSocket (backend/docs/06-live.md).
 * status: connecting | open | reconnecting | denied
 * data:   { match, timeline, liveStakes, updatedAt } — the match page reloaded after every event
 * Messages are `{type, match_id, seq, server_time, data}`: a `snapshot` first, then `event` /
 * `correction`, and `match_finished` before the server closes the socket. A bad or expired token
 * closes with 4401: get a new token and reconnect from the last `seq`.
 */
export function useLiveMatch(matchId, enabled) {
  const [state, setState] = useState({ status: 'connecting', data: null })

  useEffect(() => {
    if (!enabled) return undefined
    let ws
    let timer
    let closed = false
    let attempt = 0
    let lastSeq = 0
    let finished = false

    const retry = () => {
      attempt += 1
      setState((s) => ({ ...s, status: 'reconnecting' }))
      timer = setTimeout(connect, Math.min(1000 * 2 ** (attempt - 1), 10000))
    }

    const reload = async () => {
      try {
        const d = await api.match(matchId)
        if (!closed) setState({ status: 'open', data: { match: d.match, timeline: d.timeline, liveStakes: d.liveStakes, updatedAt: Date.now() } })
      } catch {
        /* keep what we have; the next message reloads again */
      }
    }

    async function connect() {
      let token
      try {
        token = (await api.liveToken(matchId)).token
      } catch (err) {
        if (closed) return
        if (err.status === 401 || err.status === 403) setState({ status: 'denied', data: null })
        else retry()
        return
      }
      if (closed) return
      ws = new WebSocket(api.liveUrl(matchId, token, lastSeq))
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'ping') return
        if (msg.seq != null && msg.type !== 'snapshot' && msg.seq <= lastSeq) return // each seq once, in order
        if (msg.seq != null) lastSeq = Math.max(lastSeq, msg.seq)
        attempt = 0
        if (msg.type === 'match_finished') finished = true
        reload()
      }
      ws.onclose = (ev) => {
        if (closed || finished) return
        if (ev.code === 4403) setState({ status: 'denied', data: null })
        else retry() // 4401 (token) and network drops: a new token, then since_seq
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [matchId, enabled])

  return enabled ? state : { status: 'idle', data: null }
}
