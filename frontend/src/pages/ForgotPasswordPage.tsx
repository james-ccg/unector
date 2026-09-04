import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { authApi, publicApi, errorMessage } from '../services/api'
import Turnstile from '../components/Turnstile'
import './LoginPage.css'

export default function ForgotPasswordPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  const [turnstileSiteKey, setTurnstileSiteKey] = useState<string | null>(null)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  const [turnstileNonce, setTurnstileNonce] = useState(0)

  useEffect(() => {
    publicApi.getConfig().then((c) => setTurnstileSiteKey(c.turnstile_site_key)).catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const mcNumber = new FormData(e.currentTarget).get('mc_number') as string

    try {
      await authApi.forgotPassword(mcNumber, turnstileToken)
      // Always shows the same success state regardless of whether the MC
      // number matched an account - the backend responds identically either
      // way, on purpose, so a wrong number can't be used to check who's
      // registered.
      setSent(true)
    } catch (err) {
      setError(errorMessage(err))
      setTurnstileToken(null)
      setTurnstileNonce((n) => n + 1)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="page-hero">
        <div className="container">
          <div className="page-hero-content">
            <Link to="/" className="nav-logo" style={{ display: 'inline-flex', marginBottom: '32px' }}>
              <div className="logo-icon">FP</div>
              <span className="logo-text">Unector</span>
            </Link>
            <h1 className="page-hero-title">Reset Your Password</h1>
            <p className="page-hero-description">
              Enter your company's MC number and we'll email a reset link to the address on file.
            </p>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          {sent ? (
            <div className="card form">
              <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>Check your inbox</p>
              <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.6 }}>
                If that MC number is registered, we've sent a password reset link to the email
                on file. It expires in 1 hour and can only be used once.
              </p>
              <Link to="/login" className="btn-primary btn-full" style={{ marginTop: 16, textAlign: 'center' }}>
                Back to login
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="card form">
              <label>
                <span>MC Number</span>
                <input type="text" name="mc_number" placeholder="123456" required />
              </label>
              <Turnstile key={turnstileNonce} siteKey={turnstileSiteKey} onToken={setTurnstileToken} />
              <button
                type="submit"
                className="btn-primary btn-full"
                disabled={loading || (!!turnstileSiteKey && !turnstileToken)}
              >
                {loading ? 'Sending...' : 'Send Reset Link'}
              </button>
              {error && <p className="error">{error}</p>}
              <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>
                <Link to="/login" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                  Back to login
                </Link>
              </p>
            </form>
          )}
        </div>
      </section>
    </div>
  )
}
