// Offline storage for the scorer area. Scorers work outdoors with poor signal, so:
// - the assignments list, each match's last known state and the sport's event list are kept on the phone
//   (localStorage) and used when the network fails;
// - everything the scorer enters goes into an IndexedDB queue first and is sent from there, in order,
//   until the server has it. Nothing is removed from the queue unless the server confirmed it
//   (or the scorer explicitly takes back an event that was never sent).
// Storage can be blocked (private window) or full: every call is wrapped so the page still works online.

const DB = 'oursport-scorer'
const LEGACY_DB = 'localpro-scorer'
const QUEUE = 'queue'
const META = 'meta'

function read(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

const listKey = (email) => `lp-scorer:assignments:${email ?? 'me'}`
export const saveAssignments = (email, data) => write(listKey(email), { savedAt: Date.now(), data })
/** { savedAt, data } or null */
export const loadAssignments = (email) => read(listKey(email))

export const saveSnapshot = (matchId, state) => write(`lp-scorer:match:${matchId}`, { savedAt: Date.now(), state })
export const loadSnapshot = (matchId) => read(`lp-scorer:match:${matchId}`)
export const saveEventTypes = (sport, data) => write(`lp-scorer:types:${sport}`, data)
export const loadEventTypes = (sport) => read(`lp-scorer:types:${sport}`)

/** A stable id for this phone/browser; the server de-duplicates events by (device, client sequence). */
export function deviceId() {
  let id = read('lp-scorer:device')
  if (!id) {
    id = `dev-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`
    write('lp-scorer:device', id)
  }
  return id
}

/** Next client sequence number for a match on this device (never reused, even after a reload). */
export function nextClientSeq(matchId, atLeast = 0) {
  const key = `lp-scorer:seq:${matchId}`
  const next = Math.max(read(key) ?? 0, atLeast) + 1
  write(key, next)
  return next
}

// ---- queue (IndexedDB) -----------------------------------------------------------------

function openDb() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) return reject(new Error('no IndexedDB'))
    const req = indexedDB.open(DB, 2)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(QUEUE)) {
        const store = db.createObjectStore(QUEUE, { keyPath: 'id' })
        store.createIndex('matchId', 'matchId')
      }
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META)
    }
    req.onsuccess = () => {
      const db = req.result
      migrateLegacyQueue(db).then(
        () => resolve(db),
        (error) => {
          db.close()
          reject(error)
        },
      )
    }
    req.onerror = () => reject(req.error)
  })
}

async function migrateLegacyQueue(db) {
  const migrated = await new Promise((resolve, reject) => {
    const request = db.transaction(META, 'readonly').objectStore(META).get('legacyQueueMigrated')
    request.onsuccess = () => resolve(request.result === true)
    request.onerror = () => reject(request.error)
  })
  if (migrated) return

  const records = await new Promise((resolve, reject) => {
    const request = indexedDB.open(LEGACY_DB)
    request.onupgradeneeded = (event) => {
      if (event.oldVersion === 0) request.transaction.abort()
    }
    request.onsuccess = () => {
      const legacy = request.result
      if (!legacy.objectStoreNames.contains(QUEUE)) {
        legacy.close()
        resolve([])
        return
      }
      const transaction = legacy.transaction(QUEUE, 'readonly')
      const read = transaction.objectStore(QUEUE).getAll()
      read.onsuccess = () => resolve(read.result)
      transaction.oncomplete = () => legacy.close()
      transaction.onerror = () => {
        legacy.close()
        reject(transaction.error)
      }
      transaction.onabort = () => {
        legacy.close()
        reject(transaction.error)
      }
    }
    request.onerror = () => {
      if (request.error?.name === 'AbortError') resolve([])
      else reject(request.error)
    }
  })

  await new Promise((resolve, reject) => {
    const transaction = db.transaction([QUEUE, META], 'readwrite')
    const queue = transaction.objectStore(QUEUE)
    records.forEach((record) => queue.put(record))
    transaction.objectStore(META).put(true, 'legacyQueueMigrated')
    transaction.oncomplete = resolve
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error)
  })
}

async function tx(mode, fn) {
  const db = await openDb()
  try {
    return await new Promise((resolve, reject) => {
      const t = db.transaction(QUEUE, mode)
      const result = fn(t.objectStore(QUEUE))
      t.oncomplete = () => resolve(result?.result ?? result)
      t.onerror = () => reject(t.error)
    })
  } finally {
    db.close()
  }
}

/** Save an operation before sending it: { id, matchId, order, kind: event | undo | finish, body }. */
export const enqueue = (item) => tx('readwrite', (s) => s.put({ createdAt: Date.now(), attempts: 0, error: null, ...item }))
export const updateQueued = (item) => tx('readwrite', (s) => s.put(item))
export const removeQueued = (id) => tx('readwrite', (s) => s.delete(id))

/** This match's queue in sending order. */
export async function queueFor(matchId) {
  try {
    const all = await tx('readonly', (s) => s.index('matchId').getAll(matchId))
    return [...(all ?? [])].sort((a, b) => a.order - b.order)
  } catch {
    return []
  }
}

/** Unsent operations per match: { [matchId]: count }. Empty if storage isn't available. */
export async function pendingCounts() {
  try {
    const all = (await tx('readonly', (s) => s.getAll())) ?? []
    return all.reduce((acc, it) => ({ ...acc, [it.matchId]: (acc[it.matchId] ?? 0) + 1 }), {})
  } catch {
    return {}
  }
}
