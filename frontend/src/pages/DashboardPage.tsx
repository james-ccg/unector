import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import ErrorMessage from '../components/ErrorMessage'
import Alert from '../components/Alert'
import { useAuth } from '../context/AuthContext'
import {
  dashboardApi, errorMessage,
  type Driver, type DashboardData, type DriverDetail, type LoadStage,
} from '../services/api'
import { PLAN_LABELS } from '../lib/plans'
import './DashboardPage.css'
import { formatCount, formatMoney } from '../lib/format'

// Named for what the dispatcher is waiting on next, not for the bot command
// that sets the status - "Awaiting BOL" is actionable, "loaded" isn't.
const LOAD_STAGE_LABELS: Record<LoadStage, string> = {
  dispatched: 'Awaiting pickup',
  loaded: 'Awaiting BOL',
  bol_ok: 'Awaiting POD',
}

// Matches index.css's dark theme tokens - recharts needs literal color
// values (it renders to SVG attributes, not CSS custom properties... on
// older versions; passing var(--x) does work in modern browsers via SVG's
// CSS support, but hardcoding here avoids any renderer-version surprises).
const CHART_COLORS = {
  amber: '#c3f832',
  green: '#2ecc71',
  grid: '#37342a',
  text: '#a49d8c',
  tooltipBg: '#201f17',
}

interface ChartTooltipProps {
  active?: boolean
  payload?: { dataKey: string | number; value: number }[]
  label?: string | number
  formatter?: (value: number) => string
}

function ChartTooltip({ active, payload, label, formatter }: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label && <p className="chart-tooltip-label">{label}</p>}
      {payload.map((p) => (
        <p key={p.dataKey} className="chart-tooltip-value">
          {formatter ? formatter(p.value) : p.value}
        </p>
      ))}
    </div>
  )
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [selectedDriverId, setSelectedDriverId] = useState<number | null>(null)
  const [driverDetail, setDriverDetail] = useState<DriverDetail | null>(null)
  const [driverDetailLoading, setDriverDetailLoading] = useState(false)
  const [driverDetailError, setDriverDetailError] = useState('')
  const [toggleBusy, setToggleBusy] = useState(false)

  const loadDashboard = useCallback(async () => {
    if (!user) return
    try {
      setLoading(true)
      const data = await dashboardApi.getDashboard()
      setDashboardData(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadDashboard()
  }, [loadDashboard])

  useEffect(() => {
    if (selectedDriverId === null) return
    let cancelled = false
    // Resetting the previous driver's detail/error/loading state before
    // starting the new fetch, not a side effect on external state - same
    // pattern as SettingsPage's loadAll.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDriverDetail(null)
    setDriverDetailError('')
    setDriverDetailLoading(true)
    dashboardApi
      .getDriverDetails(selectedDriverId)
      .then((data) => {
        if (!cancelled) setDriverDetail(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setDriverDetailError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setDriverDetailLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedDriverId])

  const closeDriverDetail = () => setSelectedDriverId(null)

  const handleToggleSubscription = async () => {
    if (!driverDetail) return
    const nextActive = !driverDetail.subscription_active
    setToggleBusy(true)
    setDriverDetailError('')
    try {
      await dashboardApi.toggleSubscription(driverDetail.id, nextActive)
      setDriverDetail({ ...driverDetail, subscription_active: nextActive })
      // Keep the list behind the modal in sync without a full reload.
      setDashboardData((prev) =>
        prev
          ? {
              ...prev,
              drivers: prev.drivers.map((d) =>
                d.id === driverDetail.id ? { ...d, subscription_active: nextActive } : d
              ),
            }
          : prev
      )
    } catch (err) {
      setDriverDetailError(errorMessage(err))
    } finally {
      setToggleBusy(false)
    }
  }

  // Memoized so filteredDrivers/topDriver/unassignedCount/earningsChartData
  // below don't invalidate on every render - `dashboardData?.drivers || []`
  // would otherwise create a brand-new array reference each time
  // dashboardData is null, even though the "value" hasn't changed.
  const drivers: Driver[] = useMemo(() => dashboardData?.drivers || [], [dashboardData])

  const filteredDrivers = useMemo(() => {
    return drivers
      .filter((d) => {
        if (statusFilter === 'active') return d.subscription_active
        if (statusFilter === 'inactive') return !d.subscription_active
        return true
      })
      .filter((d) => {
        if (!search.trim()) return true
        const q = search.toLowerCase()
        return (
          // Unit numbers first: with the board organised around trucks,
          // "3001" is what a dispatcher actually types to find a rig.
          d.truck?.unit_number.toLowerCase().includes(q) ||
          d.trailer?.unit_number.toLowerCase().includes(q) ||
          d.full_name?.toLowerCase().includes(q) ||
          d.driver_bot_id?.toLowerCase().includes(q) ||
          d.dispatcher_username?.toLowerCase().includes(q)
        )
      })
      .sort((a, b) => b.weekly_gross - a.weekly_gross)
  }, [drivers, search, statusFilter])

  const topDriver = useMemo(() => {
    if (drivers.length === 0) return null
    return [...drivers].sort((a, b) => b.weekly_gross - a.weekly_gross)[0]
  }, [drivers])

  const unassignedCount = useMemo(
    () => drivers.filter((d) => !d.samsara_vehicle_id).length,
    [drivers]
  )

  // Already sorted worst-first by the API (see get_fleet_status) - the order
  // is deliberately not recomputed here so both ends agree on what "needs
  // attention" means. Memoized because the `?? []` fallback would otherwise
  // be a fresh array identity on every render.
  const fleet = useMemo(() => dashboardData?.fleet ?? [], [dashboardData])
  const attentionCount = useMemo(() => fleet.filter((row) => row.attention.length > 0).length, [fleet])

  // Real per-driver earnings already fetched for the list below - just
  // reshaped for the chart, not a separate/fabricated data source.
  const earningsChartData = useMemo(
    () =>
      [...drivers]
        .sort((a, b) => b.weekly_gross - a.weekly_gross)
        .slice(0, 8)
        .map((d) => ({ name: d.full_name || d.driver_bot_id, gross: Math.round(d.weekly_gross) }))
        .reverse(),
    [drivers]
  )

  const fleetStatusData = useMemo(() => {
    const active = dashboardData?.stats?.active_drivers || 0
    const total = dashboardData?.stats?.total_drivers || 0
    const inactive = Math.max(total - active, 0)
    return [
      { name: 'Active', value: active, color: CHART_COLORS.green },
      { name: 'Inactive', value: inactive, color: CHART_COLORS.grid },
    ].filter((d) => d.value > 0)
  }, [dashboardData])

  if (loading) {
    return (
      <Layout>
        <div className="dashboard-page">
          <div className="loading-state">
            <div className="spinner"></div>
            <p>Loading dashboard...</p>
          </div>
        </div>
      </Layout>
    )
  }

  if (error) {
    return (
      <Layout>
        <div className="dashboard-page">
          <div className="error-state">
            <Icon name="warning" size={32} />
            <p>{error}</p>
            <button className="btn btn-primary" onClick={loadDashboard} style={{ marginTop: 16 }}>
              Try again
            </button>
          </div>
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="dashboard-page">
        <div className="dashboard-content container">
          <header className="page-head">
            <div>
              <p className="eyebrow">{dashboardData?.company_name || user?.companyName || '—'}</p>
              <h1>{user?.role === 'owner' ? 'Owner Dashboard' : 'Dispatcher Dashboard'}</h1>
            </div>
            {/* Only the page-level destination lives here. Settings and Sign
                out are account actions and are already in the header's
                profile menu - repeating them gave one screen two competing
                sets of the same controls, with Sign out carrying as much
                visual weight as primary navigation. */}
            <div className="page-head-actions">
              <Link to="/monitoring" className="btn btn-ghost">
                <Icon name="location" size={16} /> Live GPS
              </Link>
            </div>
          </header>

          {/* Top of the page, above the numbers: while this is broken the
              bot can't read rate confirmations at all, so every figure
              below it is quietly going stale. */}
          {dashboardData?.gmail_needs_reconnect && (
            <Alert kind="error">
              Gmail has disconnected, so new rate confirmations aren't being picked up.{' '}
              <Link to="/settings#gmail">Reconnect it in Settings</Link> to start processing loads again.
            </Alert>
          )}

          <div className="stats-row">
            <div className="stat">
              <span className="stat-value">{dashboardData?.stats?.total_drivers || 0}</span>
              <span className="stat-label">Drivers</span>
            </div>
            <div className="stat">
              <span className="stat-value">{dashboardData?.stats?.active_drivers || 0}</span>
              <span className="stat-label">Active</span>
            </div>
            <div className="stat">
              <span className="stat-value">{dashboardData?.stats?.total_loads || 0}</span>
              <span className="stat-label">Loads run</span>
            </div>
            <div className="stat">
              <span className="stat-value">{formatMoney(dashboardData?.stats?.weekly_gross)}</span>
              <span className="stat-label">Weekly gross</span>
            </div>
          </div>

          {(topDriver || unassignedCount > 0) && (
            <div className="callout-row">
              {topDriver && topDriver.weekly_gross > 0 && (
                <div className="callout">
                  <span className="callout-dot on" />
                  <span>
                    Top earner this week: <strong>{topDriver.full_name}</strong> — $
                    {formatCount(Math.round(topDriver.weekly_gross))}
                  </span>
                </div>
              )}
              {unassignedCount > 0 && (
                <div className="callout">
                  <span className="callout-dot off" />
                  <span>
                    <strong>{unassignedCount}</strong> driver{unassignedCount === 1 ? '' : 's'} without a Samsara
                    vehicle linked — GPS alerts won't work until <code>/setvehicle</code> is set.
                  </span>
                </div>
              )}
            </div>
          )}

          {user?.role === 'owner' && dashboardData?.billing && (
            <div className="card billing-card">
              <h3 className="billing-title">
                <Icon name="money" size={18} /> Subscription
              </h3>
              <div className="billing-row">
                <span className="billing-label">Plan</span>
                <span className="billing-value">{PLAN_LABELS[dashboardData.billing.tier] || dashboardData.billing.tier}</span>
              </div>
              <div className="billing-row billing-total">
                <span className="billing-label">Active drivers</span>
                <span className="billing-value">
                  {dashboardData.billing.active_drivers} / {dashboardData.billing.max_drivers}
                </span>
              </div>
              {dashboardData.billing.status === 'trialing' && dashboardData.billing.trial_ends_at && (
                <p className="billing-hint">
                  Trial ends {new Date(dashboardData.billing.trial_ends_at).toLocaleDateString()}
                </p>
              )}
              <Link to="/settings" className="billing-manage-link">Manage billing →</Link>
            </div>
          )}

          {drivers.length > 0 && (
            <div className="charts-row">
              {earningsChartData.length > 0 && (
                <div className="card chart-card">
                  <h3 className="chart-title">Weekly Gross by Driver</h3>
                  <ResponsiveContainer width="100%" height={Math.max(earningsChartData.length * 36, 120)}>
                    <BarChart data={earningsChartData} layout="vertical" margin={{ left: 8, right: 16 }}>
                      <XAxis type="number" hide />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={100}
                        tick={{ fill: CHART_COLORS.text, fontSize: 12 }}
                        axisLine={{ stroke: CHART_COLORS.grid }}
                        tickLine={false}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                        content={<ChartTooltip formatter={(v: number) => formatMoney(v)} />}
                      />
                      <Bar dataKey="gross" fill={CHART_COLORS.amber} radius={[0, 6, 6, 0]} barSize={16} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {fleetStatusData.length > 0 && (
                <div className="card chart-card chart-card-narrow">
                  <h3 className="chart-title">Fleet Status</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={fleetStatusData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={fleetStatusData.length > 1 ? 3 : 0}
                        strokeWidth={0}
                        isAnimationActive={false}
                      >
                        {fleetStatusData.map((entry) => (
                          <Cell key={entry.name} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip content={<ChartTooltip />} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="chart-legend">
                    {fleetStatusData.map((entry) => (
                      <div key={entry.name} className="chart-legend-item">
                        <span className="chart-legend-dot" style={{ background: entry.color }} />
                        <span>{entry.name}</span>
                        <span className="chart-legend-value">{entry.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Sits above the driver list because it answers the more urgent
              question - what is every truck doing right now, and which ones
              need chasing - rather than the roster question. Rows arrive
              from the API already sorted worst-first. */}
          <div className="section-header-row">
            <h2 className="section-title">Fleet status</h2>
            {fleet.length > 0 && (
              <span className="section-note">
                {attentionCount > 0
                  ? `${attentionCount} of ${fleet.length} need attention`
                  : `${fleet.length} load${fleet.length === 1 ? '' : 's'} running`}
              </span>
            )}
          </div>

          {fleet.length > 0 ? (
            <div className="fleet-list">
              {fleet.map((row) => (
                <article
                  key={`${row.driver_id}-${row.load_id}`}
                  className={`fleet-row ${row.attention.length > 0 ? 'needs-attention' : ''}`}
                >
                  <div className="fleet-main">
                    <div className="fleet-identity">
                      <span className="fleet-driver">{row.driver_name}</span>
                      <span className="fleet-load mono">#{row.load_id}</span>
                    </div>
                    <p className="fleet-route">
                      {row.pickup || '—'} <Icon name="arrow-right" size={13} /> {row.delivery || '—'}
                    </p>
                  </div>

                  <div className="fleet-meta">
                    {row.attention.map((reason) => (
                      <span key={reason} className={`fleet-flag is-${reason}`}>
                        <Icon name="warning" size={12} />
                        {reason === 'detention' ? 'In detention' : 'Past due'}
                      </span>
                    ))}
                    <span className={`fleet-stage is-${row.status}`}>{LOAD_STAGE_LABELS[row.status]}</span>
                    {row.del_date && <span className="fleet-date">Del {row.del_date}</span>}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="card">
              <p className="empty">No loads running right now. Dispatch one with <code>/dispatch</code> in Telegram.</p>
            </div>
          )}

          <div className="section-header-row">
            <h2 className="section-title">Drivers</h2>
            <div className="driver-controls">
              <input
                className="driver-search"
                type="text"
                placeholder="Search by truck, trailer, or driver..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="filter-pills">
                {(['all', 'active', 'inactive'] as const).map((f) => (
                  <button
                    key={f}
                    className={`filter-pill ${statusFilter === f ? 'is-active' : ''}`}
                    onClick={() => setStatusFilter(f)}
                  >
                    {f === 'all' ? 'All' : f === 'active' ? 'Active' : 'Inactive'}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="driver-list">
            {filteredDrivers.length > 0 ? (
              filteredDrivers.map((driver) => (
                <div
                  key={driver.id}
                  className="driver-card card"
                  onClick={() => setSelectedDriverId(driver.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') setSelectedDriverId(driver.id)
                  }}
                >
                  {/* The equipment leads, the person follows. A truck is the
                      fleet's stable unit - "where is 3001" outlives whoever
                      is driving it this month - so the unit number is the
                      heading and the driver reads as its current occupant. */}
                  <div className="driver-header">
                    <div className="driver-name-row">
                      <span className={`status-dot ${driver.subscription_active ? 'on' : 'off'}`} />
                      {/* Each unit is one indivisible chip: the label and
                          its number must never be split across a line
                          break, which is what happened when they were loose
                          inline text at two very different sizes. */}
                      <h3 className="driver-name">
                        {driver.truck ? (
                          <>
                            <span className="unit">
                              <span className="unit-label">Truck</span>
                              <span className="unit-number">{driver.truck.unit_number}</span>
                            </span>
                            {driver.trailer && (
                              <span className="unit">
                                <span className="unit-label">Trailer</span>
                                <span className="unit-number">{driver.trailer.unit_number}</span>
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-warn">No truck assigned</span>
                        )}
                      </h3>
                    </div>
                    <span className={`driver-status ${driver.subscription_active ? 'active' : 'inactive'}`}>
                      {driver.subscription_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <p className="driver-person">{driver.full_name || 'No driver assigned'}</p>
                  <div className="driver-meta-row">
                    <span className="mono">#{driver.driver_bot_id}</span>
                    {driver.dispatcher_username && <span>· {driver.dispatcher_username}</span>}
                    {driver.telegram_group_title && <span>· {driver.telegram_group_title}</span>}
                    {!driver.samsara_vehicle_id && <span className="text-warn">· no GPS vehicle linked</span>}
                  </div>
                  <div className="driver-stats">
                    <div className="driver-stat">
                      <span className="label">Total loads</span>
                      <span className="value">{driver.load_count}</span>
                    </div>
                    <div className="driver-stat">
                      <span className="label">This week</span>
                      <span className="value">{driver.weekly_loads}</span>
                    </div>
                    <div className="driver-stat">
                      <span className="label">Weekly gross</span>
                      <span className="value">{formatMoney(driver.weekly_gross)}</span>
                    </div>
                  </div>
                </div>
              ))
            ) : drivers.length === 0 ? (
              <p className="empty">
                {user?.role === 'owner' ? (
                  <>No drivers yet. <Link to="/settings">Add your first driver</Link> from Settings.</>
                ) : (
                  'No drivers yet. Ask your company owner to add one from Settings.'
                )}
              </p>
            ) : (
              <p className="empty">No drivers match your search.</p>
            )}
          </div>
        </div>
      </div>

      <AnimatePresence>
        {selectedDriverId !== null && (
          <motion.div
            className="modal-overlay"
            onClick={closeDriverDetail}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <motion.div
              className="modal-card driver-detail-card"
              onClick={(e) => e.stopPropagation()}
              initial={{ opacity: 0, scale: 0.95, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 12 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <button className="modal-close" onClick={closeDriverDetail} aria-label="Close">
                <Icon name="close" size={18} />
              </button>

              {driverDetailLoading && (
                <div className="loading-state">
                  <div className="spinner"></div>
                  <p>Loading driver...</p>
                </div>
              )}

              {!driverDetailLoading && driverDetailError && !driverDetail && (
                <ErrorMessage className="form-error" text={driverDetailError} />
              )}

              {driverDetail && (
                <>
                  <h3>{driverDetail.full_name || driverDetail.driver_bot_id}</h3>
                  <div className="driver-meta-row">
                    <span className="mono">#{driverDetail.driver_bot_id}</span>
                    {driverDetail.dispatcher_username && <span>· {driverDetail.dispatcher_username}</span>}
                    {driverDetail.telegram_group_title && <span>· {driverDetail.telegram_group_title}</span>}
                    {!driverDetail.samsara_vehicle_id && <span className="text-warn">· no GPS vehicle linked</span>}
                  </div>

                  <div className="driver-stats driver-detail-stats">
                    <div className="driver-stat">
                      <span className="label">Weekly gross</span>
                      <span className="value">{formatMoney(driverDetail.weekly_gross)}</span>
                    </div>
                    <div className="driver-stat">
                      <span className="label">Total gross</span>
                      <span className="value">{formatMoney(driverDetail.total_gross)}</span>
                    </div>
                    <div className="driver-stat">
                      <span className="label">This week</span>
                      <span className="value">{driverDetail.weekly_loads}</span>
                    </div>
                    <div className="driver-stat">
                      <span className="label">Total loads</span>
                      <span className="value">{driverDetail.total_loads}</span>
                    </div>
                  </div>

                  {(() => {
                    // Dispatchers can pause a driver (e.g. one who just quit)
                    // without waiting on the owner, but only the owner can
                    // activate one - that commits the company to another
                    // billable driver against its plan. See update_subscription
                    // in miniapp/api.py for the matching backend check.
                    const canActivate = user?.role === 'owner'
                    const activating = !driverDetail.subscription_active
                    const disabled = toggleBusy || (activating && !canActivate)
                    return (
                      <div className="subscription-toggle-row">
                        <span className={`driver-status ${driverDetail.subscription_active ? 'active' : 'inactive'}`}>
                          {driverDetail.subscription_active ? 'Subscription active' : 'Subscription inactive'}
                        </span>
                        <button
                          className={`btn ${driverDetail.subscription_active ? 'btn-ghost' : 'btn-primary'}`}
                          onClick={handleToggleSubscription}
                          disabled={disabled}
                          title={activating && !canActivate ? 'Only the company owner can activate a driver.' : undefined}
                        >
                          {toggleBusy
                            ? 'Updating...'
                            : driverDetail.subscription_active
                            ? 'Deactivate billing'
                            : 'Activate billing'}
                        </button>
                      </div>
                    )
                  })()}

                  {driverDetailError && <ErrorMessage className="form-error" text={driverDetailError} />}

                  <h4 className="load-history-title">Load history</h4>
                  {driverDetail.loads.length === 0 ? (
                    <p className="empty">No loads yet.</p>
                  ) : (
                    <div className="load-history-table-wrap">
                      <table className="load-history-table">
                        <thead>
                          <tr>
                            <th>Load</th>
                            <th>Broker</th>
                            <th>Pickup</th>
                            <th>Delivery</th>
                            <th>Rate</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {driverDetail.loads.map((load) => (
                            <tr key={load.id}>
                              <td className="mono">{load.load_id}</td>
                              <td>{load.broker_name || '—'}</td>
                              <td>{load.pu_date || '—'}</td>
                              <td>{load.del_date || '—'}</td>
                              <td>{load.rate_amount ? formatMoney(load.rate_amount) : '—'}</td>
                              <td>{load.status}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Layout>
  )
}
