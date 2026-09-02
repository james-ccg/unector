import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import FleetMap from '../components/FleetMap'
import { BASEMAPS, type BasemapId } from '../components/basemaps'
import { useAuth } from '../context/AuthContext'
import { dashboardApi, errorMessage } from '../services/api'
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
  const [error, setError] = useState('')
  const [fleetFilter, setFleetFilter] = useState<'in_transit' | 'all'>('in_transit')
  // A refresh that returns the same vehicles looks like a button that does
  // nothing. This drives a spinning icon so the click is visibly received.
  const [refreshing, setRefreshing] = useState(false)
  // Bumped to tell the map to frame the fleet again. The button lives out
  // here; the Leaflet instance lives inside FleetMap.
  const [recenterNonce, setRecenterNonce] = useState(0)
  // Always opens on Street, whatever the app's appearance is set to. No
  // mapping product ties its basemap to the surrounding interface theme,
  // and it is the wrong default anyway: a dark dashboard says nothing about
  // whether someone wants road names legible on the map inside it. Dark
  // stays on the menu as a choice.
  const [basemap, setBasemap] = useState<BasemapId>('street')
  const [layersOpen, setLayersOpen] = useState(false)

  const refresh = useCallback(async () => {
    if (!user) return
    setRefreshing(true)
    // A round trip on a fast connection can finish before the spinner has
    // drawn a frame, which reads as nothing having happened at all.
    const spunFor = new Promise((done) => setTimeout(done, 450))
    try {
      const data = await dashboardApi.getMonitoring()
      setVehicles(data.vehicles || [])
      setConnected(data.samsara_connected)
      setSelectedId((current) => current ?? data.vehicles?.[0]?.id ?? null)
      setUpdatedAt(new Date())
      setError('')
    } catch (err) {
      // Keep whatever vehicles/map we already have on screen (a stale view
      // beats a blank one) - just surface that the last refresh failed,
      // since otherwise this silently retries forever with no indication
      // the data could be minutes out of date.
      setError(errorMessage(err, "Couldn't refresh live GPS data."))
    } finally {
      await spunFor
      setRefreshing(false)
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const selected = vehicles.find((vehicle) => vehicle.id === selectedId) ?? vehicles[0]
  const located = useMemo(
    () => vehicles.filter((vehicle) => vehicle.location?.lat != null && vehicle.location?.lng != null),
    [vehicles]
  )
  const filteredVehicles = useMemo(
    () => (fleetFilter === 'in_transit' ? vehicles.filter((vehicle) => vehicle.load) : vehicles),
    [vehicles, fleetFilter]
  )

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
              <button
                className={`icon-button${refreshing ? ' is-busy' : ''}`}
                onClick={refresh}
                disabled={refreshing}
                aria-label="Refresh vehicle positions"
                title="Refresh vehicle positions"
              >
                <Icon name="refresh" size={16} />
              </button>
            </div>
            {error && (
              <p className="monitoring-error">
                <Icon name="warning" size={13} /> {error}
              </p>
            )}
            <div className="vehicle-tabs">
              <button
                className={fleetFilter === 'in_transit' ? 'active' : ''}
                onClick={() => setFleetFilter('in_transit')}
              >
                In transit <span>{vehicles.filter((item) => item.load).length}</span>
              </button>
              <button
                className={fleetFilter === 'all' ? 'active' : ''}
                onClick={() => setFleetFilter('all')}
              >
                All fleet <span>{vehicles.length}</span>
              </button>
            </div>
            <div className="vehicle-feed">
              {loading ? (
                <p className="monitoring-empty">Loading fleet...</p>
              ) : filteredVehicles.length ? (
                filteredVehicles.map((vehicle) => (
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
                  <p>
                    {vehicles.length === 0
                      ? 'No drivers are available for monitoring.'
                      : 'No vehicles are currently in transit.'}
                  </p>
                </div>
              )}
            </div>
          </aside>

          <section className="map-panel" aria-label="Live vehicle map">
            <FleetMap
              vehicles={vehicles}
              selectedId={selected?.id ?? null}
              onSelect={setSelectedId}
              recenterNonce={recenterNonce}
              basemap={basemap}
            />
            <div className="map-toolbar">
              <span>
                <span className="pulse-dot online" />
                Live map
              </span>
              {/* Was a second Refresh, with a pin on it. A pin on a map
                  means "take me to it", so now it does that - and the
                  refresh lives in exactly one place. */}
              <div className="map-layers">
                <button
                  type="button"
                  className={`map-control${layersOpen ? ' is-open' : ''}`}
                  onClick={() => setLayersOpen((open) => !open)}
                  aria-expanded={layersOpen}
                  aria-label="Map style"
                  title="Map style"
                >
                  <Icon name="layers" size={17} />
                </button>
                {layersOpen && (
                  <div className="map-layers-menu" role="radiogroup" aria-label="Map style">
                    {(Object.keys(BASEMAPS) as BasemapId[]).map((id) => (
                      <button
                        key={id}
                        type="button"
                        role="radio"
                        aria-checked={basemap === id}
                        className={basemap === id ? 'is-chosen' : undefined}
                        onClick={() => {
                          setBasemap(id)
                          setLayersOpen(false)
                        }}
                      >
                        {BASEMAPS[id].label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                className="map-control"
                onClick={() => setRecenterNonce((n) => n + 1)}
                disabled={!located.length}
                aria-label="Centre the map on the fleet"
                title={located.length ? 'Centre on the fleet' : 'No vehicle positions to centre on'}
              >
                <Icon name="location" size={18} />
              </button>
            </div>
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
                {/* Seconds, not just minutes. Without them a refresh inside the
                    same minute changes nothing on screen, which is most of
                    why the button felt dead. */}
                <strong>
                  {updatedAt
                    ? updatedAt.toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })
                    : '—'}
                </strong>
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
