import { lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'

const TruckGame = lazy(() => import('../game/TruckGame'))
const Leaderboard = lazy(() => import('../game/Leaderboard'))
import './PlayPage.css'

/** The game on its own page, reachable from the 404 and from the offline
 *  screen. Deliberately unadvertised in the nav - it's an easter egg, not a
 *  feature of the product. */
export default function PlayPage() {
  return (
    <Layout>
      <div className="play-page">
        <div className="container play-inner">
          <p className="play-eyebrow">Coffee break</p>
          <h1 className="play-title">Keep on trucking</h1>
          <p className="play-text">
            Nothing to dispatch for a minute? See how far you can get without hitting anything.
          </p>

          <Suspense fallback={<p className="play-text">Loading the yard…</p>}>
            <TruckGame />
          </Suspense>

          <Suspense fallback={null}>
            <Leaderboard />
          </Suspense>

          <p className="play-back">
            <Link to="/">← Back to Freight Pilot</Link>
          </p>
        </div>
      </div>
    </Layout>
  )
}
