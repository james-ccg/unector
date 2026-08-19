import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import TwoFactorSettings from '../components/TwoFactorSettings'
import { useAuth } from '../context/AuthContext'
import { settingsApi, dashboardApi } from '../services/api'
import './DashboardPage.css'
import './SettingsPage.css'

interface Dispatcher {
  id: number
  username: string
  role: string
  created_at: string | null
}

export default function SettingsPage() {
  const { user, logout } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [settings, setSettings] = useState<any>(null)
  const [dispatchers, setDispatchers] = useState<Dispatcher[]>([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  // Samsara "connect" modal state
  const [samsaraModalOpen, setSamsaraModalOpen] = useState(false)
  const [samsaraKey, setSamsaraKey] = useState('')
  const [samsaraBusy, setSamsaraBusy] = useState(false)
  const [samsaraError, setSamsaraError] = useState('')

  // Add-dispatcher form state
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [addDispatcherError, setAddDispatcherError] = useState('')
  const [addDispatcherBusy, setAddDispatcherBusy] = useState(false)

  const isOwner = user?.role === 'owner'

  useEffect(() => {
    loadAll()
  }, [])

  // Handle the redirect back from Google's OAuth consent screen
  // (?gmail=connected / ?gmail=error / ?gmail=error_no_refresh_token)
  useEffect(() => {
    const gmailStatus = searchParams.get('gmail')
    if (!gmailStatus) return

    if (gmailStatus === 'connected') {
      setBanner({ kind: 'success', text: 'Gmail connected successfully.' })
      loadAll()
    } else if (gmailStatus === 'error_no_refresh_token') {
      setBanner({
        kind: 'error',
        text:
          'Google didn\u2019t return a refresh token (this happens if the account was already connected before). ' +
          'Revoke access at myaccount.google.com/permissions and try connecting again.',
      })
    } else {
      setBanner({ kind: 'error', text: 'Something went wrong connecting Gmail. Please try again.' })
    }

    searchParams.delete('gmail')
    setSearchParams(searchParams, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadAll = async () => {
    if (!user) return
    try {
      const settingsData = await settingsApi.getSettings()
      setSettings(settingsData)
      if (user.role === 'owner') {
        const dispatcherData = await dashboardApi.listDispatchers()
        setDispatchers(dispatcherData)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleConnectGmail = async () => {
    if (!user) return
    try {
      const { auth_url } = await settingsApi.getGmailAuthUrl()
      // Full-page redirect to Google's own consent screen - no code to copy/paste.
      window.location.href = auth_url
    } catch (err: any) {
      setBanner({ kind: 'error', text: err.message || 'Could not start the Gmail connection.' })
    }
  }

  const handleDisconnectGmail = async () => {
    if (!user) return
    if (!confirm('Disconnect Gmail? The bot will stop being able to find Rate Confirmation emails until you reconnect.')) return
    try {
      await settingsApi.disconnectGmail()
      setBanner({ kind: 'success', text: 'Gmail disconnected.' })
      loadAll()
    } catch (err: any) {
      setBanner({ kind: 'error', text: err.message })
    }
  }

  const handleConnectSamsara = async () => {
    if (!user || !samsaraKey.trim()) return
    setSamsaraBusy(true)
    setSamsaraError('')
    try {
      await settingsApi.connectSamsara(samsaraKey.trim())
      setSamsaraModalOpen(false)
      setSamsaraKey('')
      setBanner({ kind: 'success', text: 'Samsara connected successfully.' })
      loadAll()
    } catch (err: any) {
      setSamsaraError(err.message || 'Could not connect Samsara. Double-check the API token.')
    } finally {
      setSamsaraBusy(false)
    }
  }

  const handleDisconnectSamsara = async () => {
    if (!user) return
    if (!confirm('Disconnect Samsara? GPS proximity alerts will stop working until you reconnect.')) return
    try {
      await settingsApi.disconnectSamsara()
      setBanner({ kind: 'success', text: 'Samsara disconnected.' })
      loadAll()
    } catch (err: any) {
      setBanner({ kind: 'error', text: err.message })
    }
  }

  const handleAddDispatcher = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setAddDispatcherError('')
    if (newPassword.length < 6) {
      setAddDispatcherError('Password must be at least 6 characters.')
      return
    }
    setAddDispatcherBusy(true)
    try {
      await dashboardApi.addDispatcher(newUsername.trim(), newPassword)
      setNewUsername('')
      setNewPassword('')
      setBanner({ kind: 'success', text: 'Dispatcher login created.' })
      loadAll()
    } catch (err: any) {
      setAddDispatcherError(err.message || 'Could not create that dispatcher login.')
    } finally {
      setAddDispatcherBusy(false)
    }
  }

  if (loading) {
    return (
      <Layout>
        <div className="dashboard-page">
          <div className="loading-state">
            <div className="spinner"></div>
            <p>Loading...</p>
          </div>
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
    <div className="dashboard-page">
      <div className="dashboard-content container settings-content">
        <header className="page-head">
          <div>
            <p className="eyebrow">{settings?.company_name || '—'}</p>
            <h1>Settings</h1>
          </div>
          <div className="page-head-actions">
            <Link to="/dashboard" className="btn btn-ghost">
              <Icon name="arrow-left" size={16} /> Dashboard
            </Link>
            <button className="btn btn-logout" onClick={logout}>
              <Icon name="logout" size={16} /> Log out
            </button>
          </div>
        </header>
        {banner && (
          <div className={`banner banner-${banner.kind}`}>
            <span>{banner.text}</span>
            <button className="banner-close" onClick={() => setBanner(null)}>✕</button>
          </div>
        )}

        {!isOwner && (
          <div className="banner banner-info">
            <span>You're signed in as a dispatcher. Integrations and dispatcher management are owner-only.</span>
          </div>
        )}

        {/* ---------------- Company info ---------------- */}
        <section className="settings-section">
          <h2 className="section-title">Company</h2>
          <div className="card">
            <div className="settings-row">
              <div>
                <p className="settings-row-label">Company name</p>
                <p className="settings-row-value">{settings?.company_name || '—'}</p>
              </div>
            </div>
            <div className="settings-row">
              <div>
                <p className="settings-row-label">MC number</p>
                <p className="settings-row-value mono">{settings?.mc_number || '—'}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------- Integrations ---------------- */}
        <section className="settings-section">
          <h2 className="section-title">Integrations</h2>

          <div className="card integration-card">
            <div className="integration-header">
              <div className="integration-icon"><Icon name="email" size={22} /></div>
              <div className="integration-info">
                <h3>Gmail</h3>
                <p>Lets the bot search this inbox for Rate Confirmation emails and send PODs.</p>
              </div>
              <span className={`status-badge ${settings?.gmail_connected ? 'is-connected' : 'is-disconnected'}`}>
                {settings?.gmail_connected ? 'Connected' : 'Not connected'}
              </span>
            </div>
            <div className="integration-actions">
              {settings?.gmail_connected ? (
                <button className="btn btn-danger-ghost" onClick={handleDisconnectGmail} disabled={!isOwner}>
                  Disconnect
                </button>
              ) : (
                <button className="btn btn-primary" onClick={handleConnectGmail} disabled={!isOwner}>
                  Connect Gmail
                </button>
              )}
            </div>
          </div>

          <div className="card integration-card">
            <div className="integration-header">
              <div className="integration-icon"><Icon name="location" size={22} /></div>
              <div className="integration-info">
                <h3>Samsara GPS</h3>
                <p>Powers proximity alerts ("driver is 5 miles from pickup") in the Telegram group.</p>
              </div>
              <span className={`status-badge ${settings?.samsara_connected ? 'is-connected' : 'is-disconnected'}`}>
                {settings?.samsara_connected ? 'Connected' : 'Not connected'}
              </span>
            </div>
            <div className="integration-actions">
              {settings?.samsara_connected ? (
                <button className="btn btn-danger-ghost" onClick={handleDisconnectSamsara} disabled={!isOwner}>
                  Disconnect
                </button>
              ) : (
                <button className="btn btn-primary" onClick={() => setSamsaraModalOpen(true)} disabled={!isOwner}>
                  Connect Samsara
                </button>
              )}
            </div>
          </div>
        </section>

        {/* ---------------- Dispatchers ---------------- */}
        {isOwner && (
          <section className="settings-section">
            <h2 className="section-title">Dispatchers</h2>

            <div className="card">
              {dispatchers.length > 0 ? (
                <div className="dispatcher-list">
                  {dispatchers.map((d) => (
                    <div key={d.id} className="dispatcher-row">
                      <span className="status-dot on" />
                      <span className="dispatcher-username">{d.username}</span>
                      <span className="dispatcher-role mono">{d.role}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty">No dispatcher logins yet.</p>
              )}
            </div>

            <div className="card" style={{ marginTop: 12 }}>
              <h3 className="settings-subtitle">Add a dispatcher</h3>
              <form className="form" onSubmit={handleAddDispatcher}>
                <label>
                  <span>Username</span>
                  <input
                    type="text"
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                    placeholder="new dispatcher username"
                    required
                  />
                </label>
                <label>
                  <span>Password</span>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="min. 6 characters"
                    minLength={6}
                    required
                  />
                </label>
                {addDispatcherError && <p className="form-error">{addDispatcherError}</p>}
                <button className="btn btn-primary" type="submit" disabled={addDispatcherBusy}>
                  {addDispatcherBusy ? 'Creating...' : 'Create dispatcher login'}
                </button>
              </form>
            </div>
          </section>
        )}

        {/* ---------------- Security (2FA) - available to owner and dispatcher ---------------- */}
        <section className="settings-section">
          <h2 className="section-title">Security</h2>
          <TwoFactorSettings />
        </section>
      </div>

      {/* ---------------- Samsara connect modal ---------------- */}
      {samsaraModalOpen && (
        <div className="modal-overlay" onClick={() => setSamsaraModalOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Connect Samsara</h3>
            <p className="modal-hint">
              In your Samsara dashboard: Settings (gear icon) → Developer → API Tokens → Add an API Token.
              Tag Access: Entire Organization. Permission Scope: <strong>Read Vehicle Statistics</strong> under Vehicles.
              Paste the token below.
            </p>
            <label>
              <span>Samsara API token</span>
              <input
                type="password"
                value={samsaraKey}
                onChange={(e) => setSamsaraKey(e.target.value)}
                placeholder="samsara_api_..."
                autoFocus
              />
            </label>
            {samsaraError && <p className="form-error">{samsaraError}</p>}
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setSamsaraModalOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleConnectSamsara} disabled={samsaraBusy || !samsaraKey.trim()}>
                {samsaraBusy ? 'Connecting...' : 'Connect'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </Layout>
  )
}
