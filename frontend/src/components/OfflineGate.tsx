import { lazy, Suspense, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

// Lazy, so the physics engine stays out of the bundle every visitor
// downloads - it's an easter egg, not a feature of the product. The
// chunk is warmed in the background while online (see prefetchGame), so
// it is already in the service worker's cache by the time the
// connection actually drops.
const TruckGame = lazy(() => import('../game/TruckGame'))
import Icon from './Icon'
import './OfflineGate.css'

/** Takes over the screen when the connection drops, and offers the game
 *  while the visitor waits - the same idea as Chrome's offline dino.
 *
 *  Two things are worth knowing about the limits here. navigator.onLine only
 *  reports whether the device has *a* network connection, not whether our
 *  server is reachable, so a captive portal or a dead backend still reads as
 *  online. And this can only run once the app has loaded: opening the site
 *  cold with no connection is handled by the service worker (public/sw.js),
 *  which serves the cached shell so this component gets a chance to render
 *  at all. */
export default function OfflineGate({ children }: { children: React.ReactNode }) {
  const [offline, setOffline] = useState(() => !navigator.onLine)

  useEffect(() => {
    const goOffline = () => setOffline(true)
    const goOnline = () => setOffline(false)
    window.addEventListener('offline', goOffline)
    window.addEventListener('online', goOnline)
    return () => {
      window.removeEventListener('offline', goOffline)
      window.removeEventListener('online', goOnline)
    }
  }, [])

  if (!offline) return <>{children}</>

  return (
    <div className="offline-gate">
      <div className="container offline-inner">
        <p className="offline-eyebrow">
          <Icon name="warning" size={14} /> No connection
        </p>
        <h1 className="offline-title">You&apos;re offline</h1>
        <p className="offline-text">
          Unector needs a connection to load dispatches. We&apos;ll pick up where you left
          off as soon as you&apos;re back &mdash; the page returns on its own.
        </p>

        <Suspense fallback={<p className="offline-text">Loading the yard…</p>}>
          <TruckGame />
        </Suspense>

        <p className="offline-back">
          Connection back already? <Link to="/">Reload Unector</Link>
        </p>
      </div>
    </div>
  )
}
