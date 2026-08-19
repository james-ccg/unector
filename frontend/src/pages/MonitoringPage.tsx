import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import { useAuth } from '../context/AuthContext'
import { dashboardApi } from '../services/api'
import './MonitoringPage.css'

type Vehicle = { id: number; name: string; driver_id: string; vehicle_id: string | null; active: boolean; location?: { lat?: number; lng?: number; updated_at?: string } | null; load?: { load_id: string; status: string; pickup: string; delivery: string; rate: number } | null }

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function MonitoringPage() {
  const { user } = useAuth()
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [connected, setConnected] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const refresh = useCallback(async () => {
    if (!user?.token) return
    try {
      const data = await dashboardApi.getMonitoring(user.token)
      setVehicles(data.vehicles || [])
      setConnected(data.samsara_connected)
      setSelectedId((current) => current ?? data.vehicles?.[0]?.id ?? null)
      setUpdatedAt(new Date())
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const selected = vehicles.find((vehicle) => vehicle.id === selectedId) ?? vehicles[0]
  const located = useMemo(
    () => vehicles.filter((vehicle) => vehicle.location?.lat != null && vehicle.location?.lng != null),
    [vehicles]
  )

  const positionFor = (vehicle: Vehicle) => {
    if (!vehicle.location || !located.length) return { left: '50%', top: '53%' }
    if (located.length === 1) return { left: '52%', top: '54%' }
    const lats = located.map((item) => Number(item.location?.lat))
    const lngs = located.map((item) => Number(item.location?.lng))
    const left = 14 + ((Number(vehicle.location.lng) - Math.min(...lngs)) / (Math.max(...lngs) - Math.min(...lngs) || 1)) * 72
    const top = 16 + ((Math.max(...lats) - Number(vehicle.location.lat)) / (Math.max(...lats) - Math.min(...lats) || 1)) * 67
    return { left: `${left}%`, top: `${top}%` }
  }

  return (
    <Layout>
      <main className="monitoring-page">
        <div className="container monitoring-page-head">
          <div>
            <p className="eyebrow">Fleet visibility</p>
            <h1>Live GPS</h1>
          </div>
          <Link to="/dashboard" className="btn btn-ghost">
            <Icon name="arrow-left" size={16} /> Dashboard
          </Link>
        </div>

        <div className="monitoring-shell container">
          <aside className="monitoring-list">
            <div className="monitoring-list-head">
              <div className="connection-state">
                <span className={connected ? 'pulse-dot online' : 'pulse-dot'} />
                {connected ? 'Samsara connected' : 'Samsara not connected'}
              </div>
              <button className="icon-button" onClick={refresh} aria-label="Refresh monitoring">
                <Icon name="clock" size={17} />
              </button>
            </div>
            <div className="vehicle-tabs">
              <button className="active">
                In transit <span>{vehicles.filter((item) => item.load).length}</span>
              </button>
              <button disabled>
                All fleet <span>{vehicles.length}</span>
              </button>
            </div>
            <div className="vehicle-feed">
              {loading ? (
                <p className="monitoring-empty">Loading fleet...</p>
              ) : vehicles.length ? (
                vehicles.map((vehicle) => (
                  <button
                    className={`vehicle-card ${selected?.id === vehicle.id ? 'selected' : ''}`}
                    key={vehicle.id}
                    onClick={() => setSelectedId(vehicle.id)}
                  >
                    <div className="vehicle-card-top">
                      <span className="vehicle-symbol">
                        <Icon name="truck" size={17} />
                      </span>
                      <span className={vehicle.location ? 'gps-tag live' : 'gps-tag'}>
                        {vehicle.location ? 'GPS live' : vehicle.vehicle_id ? 'Awaiting signal' : 'No vehicle linked'}
                      </span>
                    </div>
                    <strong>{vehicle.name}</strong>
                    <span className="vehicle-route">
                      {vehicle.load ? `${vehicle.load.pickup} → ${vehicle.load.delivery}` : 'No active load assigned'}
                    </span>
                    <div className="vehicle-card-foot">
                      <span>{vehicle.driver_id}</span>
                      <span className={`load-status ${vehicle.load?.status || 'idle'}`}>
                        {vehicle.load?.status?.replaceAll('_', ' ') || 'Idle'}
                      </span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="monitoring-empty">
                  <Icon name="truck" size={24} />
                  <p>No drivers are available for monitoring.</p>
                </div>
              )}
            </div>
          </aside>

          <section className="map-panel" aria-label="Live vehicle map">
            <div className="map-toolbar">
              <span>
                <span className="pulse-dot online" />
                Live map
              </span>
              <button className="map-control" onClick={refresh} aria-label="Refresh map">
                <Icon name="location" size={18} />
              </button>
            </div>
            <div className="map-label map-label-one">FREIGHT PILOT</div>
            <div className="map-label map-label-two">LIVE OPERATIONS</div>
            <svg className="route-line" viewBox="0 0 900 620" preserveAspectRatio="none" aria-hidden="true">
              <path d="M120 520 C210 430, 260 500, 340 390 S450 320, 520 270 S650 245, 780 125" />
            </svg>
            {located.map((vehicle) => (
              <button
                className={`map-vehicle ${selected?.id === vehicle.id ? 'focus' : ''}`}
                style={positionFor(vehicle)}
                key={vehicle.id}
                onClick={() => setSelectedId(vehicle.id)}
                aria-label={`Show ${vehicle.name}`}
              >
                <span>
                  <Icon name="truck" size={18} />
                </span>
                <b>{vehicle.name.split(' ')[0]}</b>
              </button>
            ))}
            {!located.length && (
              <div className="map-unavailable">
                <Icon name="location" size={27} />
                <h2>Waiting for vehicle positions</h2>
                <p>
                  {connected
                    ? 'Vehicles will appear here as Samsara reports their location.'
                    : 'Connect Samsara in Settings to enable live GPS monitoring.'}
                </p>
                {!connected && (
                  <Link to="/settings" className="btn btn-primary">
                    Open Settings
                  </Link>
                )}
              </div>
            )}
            <div className="map-grid-lines" />
          </section>
        </div>

        <section className="monitoring-detail container">
          {selected ? (
            <>
              <div>
                <p className="overline">Selected vehicle</p>
                <h2>{selected.name}</h2>
                <p>{selected.vehicle_id ? `Vehicle ${selected.vehicle_id}` : 'No Samsara vehicle linked'}</p>
              </div>
              <div>
                <small>Current load</small>
                <strong>{selected.load ? `#${selected.load.load_id}` : 'No active load'}</strong>
              </div>
              <div>
                <small>Route</small>
                <strong>{selected.load ? `${selected.load.pickup} → ${selected.load.delivery}` : 'Awaiting assignment'}</strong>
              </div>
              <div>
                <small>Rate</small>
                <strong>{selected.load ? money.format(selected.load.rate) : '—'}</strong>
              </div>
              <div>
                <small>Last refresh</small>
                <strong>{updatedAt ? updatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}</strong>
              </div>
            </>
          ) : (
            <p>Select a vehicle to view its route details.</p>
          )}
        </section>
      </main>
    </Layout>
  )
}
