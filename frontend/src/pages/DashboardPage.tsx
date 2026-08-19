import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import { useAuth } from '../context/AuthContext'
import { dashboardApi } from '../services/api'
import './DashboardPage.css'

// Matches index.css's dark theme tokens - recharts needs literal color
// values (it renders to SVG attributes, not CSS custom properties... on
// older versions; passing var(--x) does work in modern browsers via SVG's
// CSS support, but hardcoding here avoids any renderer-version surprises).
const CHART_COLORS = {
  amber: '#ff9f1c',
  green: '#2ecc71',
  grid: '#37342a',
  text: '#a49d8c',
  tooltipBg: '#201f17',
}

function ChartTooltip({ active, payload, label, formatter }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label && <p className="chart-tooltip-label">{label}</p>}
      {payload.map((p: any) => (
        <p key={p.dataKey} className="chart-tooltip-value">
          {formatter ? formatter(p.value) : p.value}
        </p>
      ))}
    </div>
  )
}

interface Driver {
  id: number
  driver_bot_id: string
  full_name: string
  telegram_group_title: string | null
  dispatcher_username: string | null
  subscription_active: boolean
  samsara_vehicle_id: string | null
  load_count: number
  weekly_gross: number
  weekly_loads: number
}

export default function DashboardPage() {
  const { user, logout } = useAuth()
  const [loading, setLoading] = useState(true)
  const [dashboardData, setDashboardData] = useState<any>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all')

  useEffect(() => {
    loadDashboard()
  }, [])

  const loadDashboard = async () => {
    if (!user) return
    try {
      setLoading(true)
      const data = await dashboardApi.getDashboard()
      setDashboardData(data)
      setError('')
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const drivers: Driver[] = dashboardData?.drivers || []

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
            <div className="page-head-actions">
              <Link to="/monitoring" className="btn btn-ghost">
                <Icon name="location" size={16} /> Live GPS
              </Link>
              <Link to="/settings" className="btn btn-ghost">
                <Icon name="settings" size={16} /> Settings
              </Link>
              <button className="btn btn-logout" onClick={logout}>
                <Icon name="logout" size={16} /> Log out
              </button>
            </div>
          </header>

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
              <span className="stat-value">${Math.round(dashboardData?.stats?.weekly_gross || 0).toLocaleString()}</span>
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
                    {Math.round(topDriver.weekly_gross).toLocaleString()}
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
                <span className="billing-label">Active drivers</span>
                <span className="billing-value">{dashboardData.billing.active_drivers}</span>
              </div>
              <div className="billing-row">
                <span className="billing-label">Price per driver</span>
                <span className="billing-value">${dashboardData.billing.price_per_driver}</span>
              </div>
              <div className="billing-row billing-total">
                <span className="billing-label">Monthly total</span>
                <span className="billing-value">${Math.round(dashboardData.billing.monthly_total).toLocaleString()}</span>
              </div>
              {dashboardData.billing.discount_applied && (
                <p className="billing-hint">Volume discount applied for {dashboardData.billing.active_drivers}+ active drivers.</p>
              )}
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
                        content={<ChartTooltip formatter={(v: number) => `$${v.toLocaleString()}`} />}
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

          <div className="section-header-row">
            <h2 className="section-title">Drivers</h2>
            <div className="driver-controls">
              <input
                className="driver-search"
                type="text"
                placeholder="Search by name, ID, or dispatcher..."
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
                <div key={driver.id} className="driver-card card">
                  <div className="driver-header">
                    <div className="driver-name-row">
                      <span className={`status-dot ${driver.subscription_active ? 'on' : 'off'}`} />
                      <h3 className="driver-name">{driver.full_name}</h3>
                    </div>
                    <span className={`driver-status ${driver.subscription_active ? 'active' : 'inactive'}`}>
                      {driver.subscription_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
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
                      <span className="value">${Math.round(driver.weekly_gross).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              ))
            ) : drivers.length === 0 ? (
              <p className="empty">No drivers yet. Add one from the Telegram bot with <code>seed.py</code>, or contact your admin.</p>
            ) : (
              <p className="empty">No drivers match your search.</p>
            )}
          </div>
        </div>
      </div>
    </Layout>
  )
}
