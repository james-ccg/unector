import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authApi, billingApi, publicApi, errorMessage } from '../services/api'
import Turnstile from '../components/Turnstile'
import './LoginPage.css'

export default function RegisterPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [turnstileSiteKey, setTurnstileSiteKey] = useState<string | null>(null)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  // Bumped to force the Turnstile widget to remount after a failed attempt -
  // Cloudflare tokens are single-use, so retrying with the same one (e.g.
  // after "MC number already registered") always fails Turnstile too.
  const [turnstileNonce, setTurnstileNonce] = useState(0)
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Once registered, either go straight to Stripe Checkout for the plan
  // picked on the Pricing page (?plan=pro&interval=month), or - for the
  // free tier / no plan param - the dashboard as usual.
  useEffect(() => {
    if (!isAuthenticated) return

    const plan = searchParams.get('plan')
    if (!plan) {
      navigate('/dashboard')
      return
    }

    const interval = (searchParams.get('interval') === 'year' ? 'year' : 'month') as 'month' | 'year'
    billingApi
      .checkout(plan as 'pro' | 'max_5x' | 'max_20x', interval)
      .then(({ url }) => {
        window.location.href = url
      })
      .catch(() => navigate('/dashboard'))
  }, [isAuthenticated, navigate, searchParams])

  useEffect(() => {
    publicApi.getConfig().then((c) => setTurnstileSiteKey(c.turnstile_site_key)).catch(() => {})
  }, [])

  const handleRegister = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setLoading(true)

    const formData = new FormData(e.currentTarget)
    const data = {
      mc_number: formData.get('mc_number') as string,
      company_name: formData.get('company_name') as string,
      email: formData.get('email') as string,
      password: formData.get('password') as string,
      confirm_password: formData.get('confirm_password') as string,
      turnstile_token: turnstileToken,
    }

    try {
      const result = await authApi.register(data)
      setSuccess('Registration successful! Redirecting...')
      login(result)
      // useEffect will handle navigation
    } catch (err) {
      setError(errorMessage(err))
      setTurnstileToken(null)
      setTurnstileNonce((n) => n + 1)
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
              <span className="logo-text">Freight Pilot</span>
            </Link>
            <h1 className="page-hero-title">Register Your Company</h1>
            <p className="page-hero-description">
              {searchParams.get('plan')
                ? 'Start your 7-day free trial today'
                : "Get started free - no card required"}
            </p>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          <form onSubmit={handleRegister} className="card form">
            <label>
              <span>Company Name</span>
              <input type="text" name="company_name" placeholder="Your Company LLC" required />
            </label>
            <label>
              <span>MC Number</span>
              <input type="text" name="mc_number" placeholder="123456" required />
            </label>
            <label>
              <span>Email</span>
              <input type="email" name="email" placeholder="owner@company.com" required />
            </label>
            <label>
              <span>Password</span>
              <input type="password" name="password" placeholder="Min. 8 characters" required minLength={8} />
            </label>
            <label>
              <span>Confirm Password</span>
              <input type="password" name="confirm_password" placeholder="Repeat password" required minLength={8} />
            </label>
            <Turnstile key={turnstileNonce} siteKey={turnstileSiteKey} onToken={setTurnstileToken} />
            <button
              type="submit"
              className="btn-primary btn-full"
              disabled={loading || (!!turnstileSiteKey && !turnstileToken)}
            >
              {loading ? 'Creating Account...' : 'Create Account'}
            </button>
            {error && <p className="error">{error}</p>}
            {success && <p className="success">{success}</p>}
            <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>
              Already have an account?{' '}
              <Link to="/login" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                Log in
              </Link>
            </p>
          </form>

          <p style={{ textAlign: 'center', marginTop: '24px', color: 'var(--text-muted)', fontSize: '14px' }}>
            <Link to="/" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
              ← Back to Home
            </Link>
          </p>
        </div>
      </section>
    </div>
  )
}
