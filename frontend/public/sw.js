/* Service worker: just enough caching that the app shell still loads with no
 * connection, so OfflineGate can render the offline screen and the game.
 *
 * Without this there is nothing to run: with no network the browser never
 * reaches our server, shows its own error page, and no amount of in-app
 * offline handling gets a chance. This is the piece that makes "open the site
 * with no internet" actually work rather than only "lose connection while
 * already open".
 *
 * Deliberately narrow: it caches the built shell and static assets, and never
 * touches /api. Caching API responses would mean showing stale dispatch data
 * as though it were current, which is worse than showing nothing.
 */
const CACHE = 'unector-shell-v1'
const SHELL = '/index.html'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll([SHELL, '/'])).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // Never cache the API or anything cross-origin. Stale loads, rates or GPS
  // positions presented as live would be actively misleading.
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api')) {
    return
  }

  // Navigations: network first so a connected visitor always gets the current
  // build, falling back to the cached shell when there's nothing to reach.
  // The SPA router then resolves whatever path they asked for.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(SHELL, copy))
          return response
        })
        .catch(() => caches.match(SHELL).then((hit) => hit || Response.error()))
    )
    return
  }

  // Hashed build assets are immutable, so cache-first is safe and makes the
  // offline screen render instantly.
  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) return hit
      return fetch(request)
        .then((response) => {
          if (response.ok && response.type === 'basic') {
            const copy = response.clone()
            caches.open(CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(() => hit || Response.error())
    })
  )
})
