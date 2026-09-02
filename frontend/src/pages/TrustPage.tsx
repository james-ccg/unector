import { useState, useEffect } from 'react'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import Alert from '../components/Alert'
import { publicApi, errorMessage } from '../services/api'
import { formatCount } from '../lib/format'

interface Stats {
  companies: number
  active_trucks: number
  loads_delivered: number
}

export default function TrustPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  // A failed fetch used to be swallowed, leaving `stats` null and every
  // counter rendering a confident 0 - the page claimed no customers rather
  // than admitting it could not reach the server. Now it says which.
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await publicApi.getStats()
        if (!cancelled) setStats(data)
      } catch (err) {
        console.error('Failed to load stats:', err)
        if (!cancelled) setError(errorMessage(err, "Couldn't load the numbers."))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">
              <Icon name="shield" size={28} /> Trust &amp; Platform Stats
            </h1>
            <p className="page-description">
              Counted from our own database when you loaded this page. Freight Pilot started in
              August 2026, so these are small numbers - they are also the real ones, which is the
              only reason to put them on a page at all.
            </p>
          </div>

          {error && <Alert kind="error">{error}</Alert>}

          <div className="stats-showcase">
            <div className="stat-card card">
              <div className="stat-number">{loading || error ? '—' : stats?.companies ?? 0}</div>
              <div className="stat-label">Companies</div>
              <p className="stat-desc">Carriers running dispatch through Freight Pilot</p>
            </div>

            <div className="stat-card card">
              <div className="stat-number">{loading || error ? '—' : formatCount(stats?.active_trucks ?? 0)}</div>
              <div className="stat-label">Active Drivers</div>
              <p className="stat-desc">Drivers currently managed through the platform</p>
            </div>

            <div className="stat-card card">
              <div className="stat-number">{loading || error ? '—' : formatCount(stats?.loads_delivered ?? 0)}</div>
              <div className="stat-label">Loads Processed</div>
              <p className="stat-desc">Rate confirmations extracted and tracked</p>
            </div>

          </div>

          <div className="testimonials">
            <h2 className="section-title">What Freight Pilot Automates</h2>
            <p className="page-description" style={{ marginBottom: 32 }}>
              We're an early-stage platform - here's exactly what's running under the hood today,
              not marketing claims.
            </p>
            <div className="testimonial-grid">
              <div className="testimonial-card card">
                <Icon name="email" size={22} />
                <p className="testimonial-text" style={{ marginTop: 12 }}>
                  Rate Confirmations are found automatically by searching the connected inbox, and
                  every field - broker, pickup/delivery, weight, rate - is extracted by AI in seconds.
                </p>
              </div>

              <div className="testimonial-card card">
                <Icon name="check" size={22} />
                <p className="testimonial-text" style={{ marginTop: 12 }}>
                  Load photos and BOLs are checked against the RC automatically - seal numbers,
                  weight limits, and temperature requirements are cross-referenced before a driver
                  gets a "good to go."
                </p>
              </div>

              <div className="testimonial-card card">
                <Icon name="location" size={22} />
                <p className="testimonial-text" style={{ marginTop: 12 }}>
                  Once Samsara is connected, the platform watches GPS proximity to pickup and
                  delivery and notifies dispatch automatically - no one has to babysit a map.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
