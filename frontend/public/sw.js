// Service worker: keeps the app shell (HTML, JS, CSS) so the scorer pages open without a connection.
// API data is not cached here; the pages keep their own offline copies (see areas/scorer/offlineStore.js).
const CACHE = 'oursport-shell-v2'

// Cache the page and the files it loads (their names change with every build, so read them from the HTML).
async function precache() {
  const cache = await caches.open(CACHE)
  const res = await fetch('/', { cache: 'no-store' })
  const html = await res.clone().text()
  const files = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1])
  await cache.put('/', res)
  await cache.addAll(['/favicon.svg', ...files])
}

self.addEventListener('install', (e) => {
  e.waitUntil(precache().then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== self.location.origin) return
  if (req.mode === 'navigate') {
    // pages: network first, the cached shell when offline
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put('/', copy))
          return res
        })
        .catch(() => caches.match('/')),
    )
  } else if (url.pathname.startsWith('/assets/')) {
    // built files have hashed names: cache first
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone()
        caches.open(CACHE).then((c) => c.put(req, copy))
        return res
      })),
    )
  }
})
