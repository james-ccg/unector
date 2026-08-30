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
