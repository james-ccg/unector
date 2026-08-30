import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import ScrollToTop from './components/ScrollToTop'
import ErrorBoundary from './components/ErrorBoundary'
import OfflineGate from './components/OfflineGate'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <ScrollToTop />
        {/* Inside the router, because the offline screen links back into the
            app; outside App so it replaces every route at once rather than
            each page handling it. */}
        <OfflineGate>
          <App />
        </OfflineGate>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
)

// Registered after paint so it never competes with the first render. Only in
// production: in dev it would serve a stale shell over Vite's HMR and make
// changes appear not to take.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // Not fatal - the app works fine without it, it just won't open
      // offline.
    })
  })
}

/** Pulls the game's chunk down quietly once the page is idle and online.
 *
 * The game is lazy so the physics engine isn't in everyone's first load, but
 * that alone would make it unavailable in exactly the situation it exists
 * for: a visitor who never opened /play has nothing cached when the
 * connection drops. Fetching it during idle time puts it through the service
 * worker - and therefore into the cache - long before it's needed, at no cost
 * to the initial render. */
function prefetchGame() {
  if (!navigator.onLine) return
  import('./game/TruckGame').catch(() => {
    // Offline already, or the chunk 404s after a deploy - either way the
    // lazy import will simply try again when the game is actually opened.
  })
}

if ('requestIdleCallback' in window) {
  ;(window as Window & { requestIdleCallback: (cb: () => void) => void }).requestIdleCallback(prefetchGame)
} else {
  setTimeout(prefetchGame, 3000)
}
