import { useState, useEffect } from 'react'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import { publicApi } from '../services/api'
import { formatCount } from '../lib/format'

interface Stats {
  companies: number
  active_trucks: number
  loads_delivered: number
}

export default function TrustPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await publicApi.getStats()
        if (!cancelled) setStats(data)
      } catch (err) {
        console.error('Failed to load stats:', err)
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
              Live numbers pulled directly from our database - updated in real time as the platform grows.
            </p>
          </div>

          <div className="stats-showcase">
            <div className="stat-card card">
              <div className="stat-number">{loading ? '—' : stats?.companies ?? 0}</div>
              <div className="stat-label">Companies</div>
              <p className="stat-desc">Carriers running dispatch through Freight Pilot</p>
            </div>

            <div className="stat-card card">
              <div className="stat-number">{loading ? '—' : formatCount(stats?.active_trucks ?? 0)}</div>
              <div className="stat-label">Active Drivers</div>
              <p className="stat-desc">Drivers currently managed through the platform</p>
            </div>

            <div className="stat-card card">
              <div className="stat-number">{loading ? '—' : formatCount(stats?.loads_delivered ?? 0)}</div>
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
