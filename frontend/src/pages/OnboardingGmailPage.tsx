import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { settingsApi, errorMessage } from '../services/api'
import Icon from '../components/Icon'
import { gmailErrorMessage } from '../lib/gmailError'
import './LoginPage.css'

export default function OnboardingGmailPage() {
  const { user, logout, refreshUser, isLoading } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  // Dispatchers never hit this gate, and an owner who already connected
  // Gmail (e.g. navigated here directly by URL) has nothing left to do here.
  useEffect(() => {
    if (isLoading) return
    if (!user) return
    if (user.role !== 'owner' || user.gmailConnected) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, isLoading, navigate])

  // Handle the redirect back from Google's OAuth consent screen.
  useEffect(() => {
    const gmailStatus = searchParams.get('gmail')
    if (!gmailStatus) return

    if (gmailStatus === 'connected') {
      refreshUser().then(() => navigate('/dashboard', { replace: true }))
      return
    }
    // Deferred a tick so this isn't a same-render-cycle setState
    // (react-hooks/set-state-in-effect) - purely cosmetic timing-wise,
    // since a microtask still runs before the next paint. Same pattern as
    // SettingsPage's gmail-redirect handling.
    queueMicrotask(() => {
      setError(gmailErrorMessage(gmailStatus, searchParams.get('reason')) ?? '')
    })
    searchParams.delete('gmail')
    setSearchParams(searchParams, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleConnect = async () => {
    setError('')
    setConnecting(true)
    try {
      const { auth_url } = await settingsApi.getGmailAuthUrl('onboarding')
      window.location.href = auth_url
    } catch (err) {
      setError(errorMessage(err, "Couldn't start the Gmail connection."))
      setConnecting(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="page-hero">
        <div className="container">
          <div className="page-hero-content">
            <div className="logo-icon" style={{ margin: '0 auto 24px' }}>FP</div>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 8 }}>
              STEP 2 OF 2
            </p>
            <h1 className="page-hero-title">Connect Gmail to Finish Setup</h1>
            <p className="page-hero-description">
              Unector reads rate confirmations straight from your inbox, so dispatch runs
              automatically - without this, that's still manual. It's a one-time step and takes
              under a minute.
            </p>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          <div className="card form">
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <Icon name="email" size={22} />
              <div>
                <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>
                  Secure OAuth connection
                </p>
                <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
                  You'll approve access on Google's own consent screen - Unector never
                  sees your password, and you can revoke access any time from Settings.
                </p>
              </div>
            </div>

            <button className="btn-primary btn-full" onClick={handleConnect} disabled={connecting}>
              {connecting ? 'Redirecting to Google...' : 'Connect Gmail'}
            </button>
            {error && <p className="error">{error}</p>}

            <button
              type="button"
              className="btn-ghost btn-full"
              onClick={logout}
              style={{ marginTop: 8 }}
            >
              Log out instead
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
