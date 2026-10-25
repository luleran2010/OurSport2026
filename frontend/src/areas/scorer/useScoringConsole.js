import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useOnline } from '../../live/useOnline'
import {
  deviceId as getDeviceId, enqueue, loadEventTypes, loadSnapshot, nextClientSeq, queueFor, removeQueued, saveEventTypes,
  saveSnapshot, updateQueued,
} from './offlineStore'

const BACKOFF = [1, 2, 5, 10, 30] // seconds between retries after a network failure

/** Load the match from the server (falls back to the copy on the phone). Pure: returns what to apply. */
async function loadMatch(matchId, device) {
  const queue = await queueFor(matchId)
  try {
    const state = await api.scoringState(matchId, device)
    let types = loadEventTypes(state.sport)
    try {
      types = await api.eventTypes(state.sport)
      saveEventTypes(state.sport, types)
    } catch {
      /* keep the saved list */
    }
    return { queue, state, types, load: { status: 'ready', error: null, offline: false } }
  } catch (err) {
    if (err.status) return { queue, load: { status: 'error', error: err, offline: false } }
    const snap = loadSnapshot(matchId)?.state // no answer: offline
    return { queue, load: { status: snap ? 'ready' : 'error', error: err, offline: true } }
  }
}

/** Send the queue in order, one operation at a time, until it's empty, refused or the network fails. */
async function sendQueue(matchId, device, attempt) {
  let last = null
  let retryAt = null
  let q = await queueFor(matchId)
  while (q.length) {
    const item = q[0]
    if (item.error) break // a refused operation blocks the ones after it until the scorer decides
    try {
      if (item.kind === 'event') last = await api.postEvent(matchId, item.body)
      else if (item.kind === 'undo') last = await api.undoEvent(matchId, item.body.clientSeq, item.body.deviceId, item.body.undoSeq)
      else {
        await api.finishScoring(matchId, item.body.score)
        last = await api.scoringState(matchId, device)
      }
      await removeQueued(item.id) // only now, after the server confirmed it
      attempt.current = 0
    } catch (err) {
      if (!err.status) {
        retryAt = Date.now() + BACKOFF[Math.min(attempt.current, BACKOFF.length - 1)] * 1000 // keep it, try later
        attempt.current += 1
        await updateQueued({ ...item, attempts: (item.attempts ?? 0) + 1 })
      } else {
        await updateQueued({ ...item, attempts: (item.attempts ?? 0) + 1, error: { status: err.status, message: err.message } })
      }
      break
    }
    q = await queueFor(matchId)
  }
  return { last, retryAt, queue: await queueFor(matchId) }
}

/**
 * Scoring console state (S2), offline first:
 * 1. every tap becomes an operation with a client sequence number, saved to IndexedDB;
 * 2. a sender works through the queue in order and POSTs each operation (the server ignores repeats);
 * 3. what the scorer sees = the server's last state + the operations still in the queue.
 * The server is the source of truth; the local arithmetic only bridges the time without a connection.
 */
export function useScoringConsole(matchId) {
  const online = useOnline()
  const [device] = useState(getDeviceId)
  const [server, setServer] = useState(() => loadSnapshot(matchId)?.state ?? null)
  const [types, setTypes] = useState(() => {
    const snap = loadSnapshot(matchId)?.state
    return snap ? loadEventTypes(snap.sport) : null
  })
  const [queue, setQueue] = useState([])
  const [load, setLoad] = useState({ status: 'loading', error: null, offline: false })
  const [retryAt, setRetryAt] = useState(null)
  const [kick, setKick] = useState(0) // bump to (re)start the sender
  const [version, setVersion] = useState(0) // bump to reload from the server
  const busy = useRef(false)
  const attempt = useRef(0)

  const acceptServer = (state) => {
    setServer(state)
    saveSnapshot(matchId, state)
  }

  const applyLoad = useEffectEvent((r) => {
    setQueue(r.queue)
    if (r.state) {
      acceptServer(r.state)
      nextClientSeq(matchId, r.state.deviceLastSeq) // never reuse a number the server already has
    }
    if (r.types) setTypes(r.types)
    setLoad(r.load)
    setKick((k) => k + 1)
  })
  useEffect(() => {
    loadMatch(matchId, device).then(applyLoad)
  }, [matchId, device, online, version]) // back online: resync, then send what waited

  const applySend = useEffectEvent((r) => {
    busy.current = false
    if (r.last) acceptServer(r.last)
    setQueue(r.queue)
    setRetryAt(r.retryAt)
    if (!r.retryAt && r.queue.length && !r.queue[0].error) setKick((k) => k + 1) // more arrived while sending
  })
  useEffect(() => {
    if (!online) return
    const wait = retryAt ? Math.max(0, retryAt - Date.now()) : 0
    const t = setTimeout(() => {
      if (busy.current) return
      busy.current = true
      sendQueue(matchId, device, attempt).then(applySend)
    }, wait)
    return () => clearTimeout(t)
  }, [kick, retryAt, online, matchId, device])

  // ---- actions (from taps) -----------------------------------------------------------------

  const after = async () => {
    setQueue(await queueFor(matchId))
    setRetryAt(null)
    setKick((k) => k + 1)
  }
  const order = () => Date.now() * 1000 + Math.floor(Math.random() * 1000)

  const record = async (type, team, playerId) => {
    const clientSeq = nextClientSeq(matchId, server?.deviceLastSeq ?? 0)
    await enqueue({
      id: `${matchId}:e${clientSeq}`, matchId, order: order(), kind: 'event',
      body: { deviceId: device, clientSeq, type, team: team ?? null, playerId: playerId ?? null, at: Date.now() },
    })
    await after()
  }

  /** Take back an event: still on the phone -> remove it; already sent (or being sent) -> queue an undo. */
  const undo = async (ev) => {
    const queued = queue.find((q) => q.kind === 'event' && q.body.clientSeq === ev.clientSeq && q.body.deviceId === ev.deviceId)
    if (queued && !busy.current) await removeQueued(queued.id)
    else {
      // the undo is a new event on the server, with its own sequence number
      const undoSeq = nextClientSeq(matchId, server?.deviceLastSeq ?? 0)
      await enqueue({ id: `${matchId}:u${ev.deviceId}:${ev.clientSeq}`, matchId, order: order(), kind: 'undo',
        body: { clientSeq: ev.clientSeq, deviceId: ev.deviceId, undoSeq } })
    }
    await after()
  }

  const finish = async (score) => {
    await enqueue({ id: `${matchId}:finish`, matchId, order: order(), kind: 'finish', body: { score } })
    await after()
  }

  const retry = async () => {
    for (const item of queue.filter((q) => q.error)) await updateQueued({ ...item, error: null })
    attempt.current = 0
    await after()
  }

  const discard = async (item) => {
    await removeQueued(item.id)
    await after()
  }

  return {
    device, online, server, types, queue, load, retryAt,
    record, undo, finish, retry, discard, reload: () => setVersion((v) => v + 1),
  }
}

/**
 * What the console shows: the server state with the queued operations applied on top.
 * Returns { score, wickets, balls, started, between, periodIndex, finished, events (newest first) }.
 */
export function project(server, queue, types) {
  const byId = Object.fromEntries((types?.eventTypes ?? []).map((t) => [t.id, t]))
  const v = {
    score: [...(server.match.score ?? [0, 0])],
    wickets: [...server.wickets],
    balls: [...server.balls],
    started: server.started,
    between: server.betweenPeriods,
    periodIndex: server.periodIndex,
    finished: server.match.status === 'finished',
    events: server.events.map((e) => ({ ...e, state: 'synced' })),
  }
  const apply = (et, side, sign) => {
    if (side == null) return
    if (et.points) v.score[side] = Math.max(0, v.score[side] + sign * et.points)
    if (et.wicket) v.wickets[side] = Math.max(0, v.wickets[side] + sign)
    if (et.ball) v.balls[side] = Math.max(0, v.balls[side] + sign)
  }
  for (const q of queue) {
    const state = q.error ? 'failed' : 'queued'
    if (q.kind === 'event') {
      const et = byId[q.body.type]
      if (!et) continue
      const side = q.body.team === 'home' ? 0 : q.body.team === 'away' ? 1 : null
      if (et.id === 'start') Object.assign(v, { started: true, periodIndex: 0, between: false })
      else if (et.id === 'period_end') v.between = true
      else if (et.id === 'period_start') Object.assign(v, { between: false, periodIndex: v.periodIndex + 1 })
      else apply(et, side, 1)
      v.events.unshift({ seq: null, clientSeq: q.body.clientSeq, deviceId: q.body.deviceId, type: q.body.type, team: q.body.team,
        playerId: q.body.playerId, playerLabel: null, minute: null, at: q.body.at, undone: false, state, queueItem: q })
    } else if (q.kind === 'undo') {
      const ev = v.events.find((e) => e.clientSeq === q.body.clientSeq && e.deviceId === q.body.deviceId && !e.undone)
      if (ev) {
        ev.undone = true
        ev.state = state
        const et = byId[ev.type]
        if (et) apply(et, ev.team === 'home' ? 0 : ev.team === 'away' ? 1 : null, -1)
      }
    } else if (q.kind === 'finish') {
      v.finished = true
      v.score = q.body.score
    }
  }
  return v
}
