import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authApi, billingApi, publicApi, errorMessage } from '../services/api'
import Turnstile from '../components/Turnstile'
import { turnstileUnavailableMessage } from '../lib/turnstile'
import PasswordInput from '../components/PasswordInput'
import { gmailErrorMessage } from '../lib/gmailError'
import './LoginPage.css'

// Registration is Gmail-first: connect Gmail, confirm you own that inbox
// (code or link emailed to it), THEN fill in company details - a company
// is only ever created at the final submit, so abandoning anywhere before
// that (closing the tab, never verifying, never finishing the form) leaves
// nothing behind. See PendingRegistration's docstring in db/models.py.
type Step = 'connect-gmail' | 'verify-email' | 'company-details'

// Google's OAuth redirect only carries back whatever the backend's own
// callback puts in the URL (pending_token, or an error flag) - a ?plan=
// picked on the Pricing page would otherwise be lost across that round
// trip, so it's stashed here instead and read back on return.
const PLAN_STORAGE_KEY = 'un-register-plan'

export default function RegisterPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [turnstileSiteKey, setTurnstileSiteKey] = useState<string | null>(null)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  // Why the check could not run, when it could not. The submit button is
  // already disabled without a token, so without this the form is simply
  // dead with nothing on screen saying why.
  const [turnstileError, setTurnstileError] = useState<string | null>(null)
  // Bumped to force the Turnstile widget to remount after a failed attempt -
  // Cloudflare tokens are single-use, so retrying with the same one (e.g.
  // after "MC number already registered") always fails Turnstile too.
  const [turnstileNonce, setTurnstileNonce] = useState(0)
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const pendingToken = searchParams.get('pending_token')
  const [step, setStep] = useState<Step>(pendingToken ? 'verify-email' : 'connect-gmail')
  const [gmailEmail, setGmailEmail] = useState('')
  const [connectError, setConnectError] = useState('')
  const [connectBusy, setConnectBusy] = useState(false)

  const [verifyCode, setVerifyCode] = useState('')
  const [verifyError, setVerifyError] = useState('')
  const [verifyBusy, setVerifyBusy] = useState(false)
  const [resendBusy, setResendBusy] = useState(false)
  const [resendMessage, setResendMessage] = useState('')

  const plan = typeof window !== 'undefined' ? sessionStorage.getItem(PLAN_STORAGE_KEY) : null

  // Surfaces the Gmail OAuth callback's error flags (?gmail=error/...).
  useEffect(() => {
    const gmailStatus = searchParams.get('gmail')
    if (!gmailStatus) return
    queueMicrotask(() => {
      setConnectError(gmailErrorMessage(gmailStatus, searchParams.get('reason')) ?? '')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Resolves what step to show once a pending_token shows up in the URL -
  // from either the Gmail callback redirect or clicking the verify-link
  // straight from the confirmation email.
  useEffect(() => {
    if (!pendingToken) return
    const alreadyVerified = searchParams.get('verified') === '1'

    authApi
      .registerPendingStatus(pendingToken)
      .then((status) => {
        setGmailEmail(status.gmail_email)
        setStep(status.email_verified || alreadyVerified ? 'company-details' : 'verify-email')
      })
      .catch(() => {
        setConnectError('That Gmail connection is invalid or has expired. Please connect Gmail again.')
        setStep('connect-gmail')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingToken])

  // Once registered, either go straight to Stripe Checkout for the plan
  // picked on the Pricing page, or - for the free tier / no plan - the
  // dashboard as usual.
  useEffect(() => {
    if (!isAuthenticated) return

    if (!plan) {
      navigate('/dashboard')
      return
    }
    sessionStorage.removeItem(PLAN_STORAGE_KEY)

    const interval = (sessionStorage.getItem('un-register-interval') === 'year' ? 'year' : 'month') as 'month' | 'year'
    billingApi
      .checkout(plan as 'pro' | 'max_5x' | 'max_20x', interval)
      .then(({ url }) => {
        window.location.href = url
      })
      .catch(() => navigate('/dashboard'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, navigate])

  useEffect(() => {
    publicApi.getConfig().then((c) => setTurnstileSiteKey(c.turnstile_site_key)).catch(() => {})
  }, [])

  const handleConnectGmail = async () => {
    setConnectError('')
    setConnectBusy(true)
    // Remember the plan across the OAuth round-trip (see PLAN_STORAGE_KEY).
    const planParam = searchParams.get('plan')
    if (planParam) {
      sessionStorage.setItem(PLAN_STORAGE_KEY, planParam)
      sessionStorage.setItem('un-register-interval', searchParams.get('interval') === 'year' ? 'year' : 'month')
    }
    try {
      const { auth_url } = await authApi.registerGmailStart()
      window.location.href = auth_url
    } catch (err) {
      setConnectError(errorMessage(err, "Couldn't start the Gmail connection."))
      setConnectBusy(false)
    }
  }

  const handleVerifyCode = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!pendingToken) return
    setVerifyError('')
    setVerifyBusy(true)
    try {
      await authApi.registerVerifyCode(pendingToken, verifyCode.trim())
      setStep('company-details')
    } catch (err) {
      setVerifyError(errorMessage(err, 'Incorrect or expired code.'))
    } finally {
      setVerifyBusy(false)
    }
  }

  const handleResend = async () => {
    if (!pendingToken) return
    setResendBusy(true)
    setResendMessage('')
    try {
      await authApi.registerResendVerification(pendingToken)
      setResendMessage('Sent - check your inbox.')
    } catch (err) {
      setVerifyError(errorMessage(err, "Couldn't resend the email."))
    } finally {
      setResendBusy(false)
    }
  }

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
      pending_token: pendingToken,
    }

    try {
      const result = await authApi.register(data)
      setSuccess(plan ? 'Account created - taking you to checkout...' : 'Account created - taking you to your dashboard...')
      login(result)
      // useEffect will handle navigation
    } catch (err) {
      setError(errorMessage(err))
      setTurnstileToken(null)
      setTurnstileError(null)
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
              <div className="logo-icon">UN</div>
              <span className="logo-text">Unector</span>
            </Link>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 8 }}>
              STEP {step === 'connect-gmail' ? '1' : step === 'verify-email' ? '2' : '3'} OF 3
            </p>
            <h1 className="page-hero-title">Register Your Company</h1>
            <p className="page-hero-description">
              {step === 'connect-gmail' && 'Connect Gmail first, so dispatch can start pulling in rate confirmations right away.'}
              {step === 'verify-email' && 'Confirm this is your inbox to continue.'}
              {step === 'company-details' &&
                (plan
                  ? "Start your 7-day free trial. It asks for a payment method so the plan can carry on when the trial ends - nothing is charged until that day, and you can cancel before it."
                  : 'Get started free - no card required')}
            </p>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          {step === 'connect-gmail' && (
            <div className="card form">
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <div>
                  <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>Secure OAuth connection</p>
                  <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
                    You'll approve access on Google's own consent screen - Unector never sees your
                    password, and you can revoke access any time from Settings.
                  </p>
                </div>
              </div>
              <button className="btn-primary btn-full" onClick={handleConnectGmail} disabled={connectBusy}>
                {connectBusy ? 'Redirecting to Google...' : 'Connect Gmail'}
              </button>
              {connectError && <p className="error">{connectError}</p>}
              <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>
                Already have an account?{' '}
                <Link to="/login" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                  Log in
                </Link>
              </p>
            </div>
          )}

          {step === 'verify-email' && (
            <form onSubmit={handleVerifyCode} className="card form">
              <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>Check your inbox</p>
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.5 }}>
                We sent a confirmation to <strong>{gmailEmail}</strong> - click the link in that email, or
                enter the 6-digit code below.
              </p>
              <label>
                <span>Verification code</span>
                <input
                  type="text"
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value)}
                  placeholder="123456"
                  inputMode="numeric"
                  autoFocus
                  required
                />
              </label>
              <button type="submit" className="btn-primary btn-full" disabled={verifyBusy || !verifyCode.trim()}>
                {verifyBusy ? 'Verifying...' : 'Verify'}
              </button>
              {verifyError && <p className="error">{verifyError}</p>}
              <button
                type="button"
                className="btn-secondary btn-full"
                onClick={handleResend}
                disabled={resendBusy}
              >
                {resendBusy ? 'Sending...' : 'Resend email'}
              </button>
              {resendMessage && <p className="success">{resendMessage}</p>}
            </form>
          )}

          {step === 'company-details' && (
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
                <input type="email" name="email" defaultValue={gmailEmail} placeholder="owner@company.com" required />
              </label>
              <label>
                <span>Password</span>
                <PasswordInput name="password" placeholder="Min. 8 characters" required minLength={8} />
              </label>
              <label>
                <span>Confirm Password</span>
                <PasswordInput name="confirm_password" placeholder="Repeat password" required minLength={8} />
              </label>
              <Turnstile
                    key={turnstileNonce}
                    siteKey={turnstileSiteKey}
                    onToken={setTurnstileToken}
                    onUnavailable={setTurnstileError}
                  />
                  {turnstileError && (
                    <p className="error">{turnstileUnavailableMessage(turnstileError)}</p>
                  )}
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
          )}

          <p style={{ textAlign: 'center', marginTop: '20px', color: 'var(--text-muted)', fontSize: '13px', lineHeight: 1.5 }}>
            Your password is encrypted and never visible to anyone at Unector, including us.
            We'll only ever email you about your own account.
          </p>

          <p style={{ textAlign: 'center', marginTop: '16px', color: 'var(--text-muted)', fontSize: '14px' }}>
            <Link to="/" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
              ← Back to Home
            </Link>
          </p>
        </div>
      </section>
    </div>
  )
}
