import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import { useAuth } from '../context/AuthContext'
import { dashboardApi } from '../services/api'
import './DashboardPage.css'

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
