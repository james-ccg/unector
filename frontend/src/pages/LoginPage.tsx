import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authApi, twoFaApi, publicApi, errorMessage } from '../services/api'
import type { LoginSuccess, TwoFaChallenge } from '../services/api'
import { isWebAuthnSupported, getCredential } from '../services/webauthn'
import Turnstile from '../components/Turnstile'
import './LoginPage.css'

const METHOD_LABELS: Record<string, string> = {
  totp: 'Authenticator app',
  email: 'Email code',
  sms: 'Text message',
  telegram: 'Telegram',
  webauthn: 'Security key',
}

function isChallenge(data: LoginSuccess | TwoFaChallenge): data is TwoFaChallenge {
  return (data as TwoFaChallenge).requires_2fa === true
}

export default function LoginPage() {
  const [activeTab, setActiveTab] = useState<'owner' | 'dispatcher'>('owner')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()

  // 2FA step state
  const [challenge, setChallenge] = useState<TwoFaChallenge | null>(null)
  const [method, setMethod] = useState<string>('')
  const [code, setCode] = useState('')
  const [codeSent, setCodeSent] = useState(false)

  const [turnstileSiteKey, setTurnstileSiteKey] = useState<string | null>(null)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  // Bumped to force the Turnstile widget to remount (and issue a fresh
  // token) after a failed attempt or a tab switch. Cloudflare tokens are
  // single-use - once verify_turnstile has checked one, submitting it again
  // (e.g. retrying after a wrong password, or switching from the Owner tab
  // to the Dispatcher tab) always fails with "Bot verification failed",
  // regardless of whether the credentials themselves are right.
  const [turnstileNonce, setTurnstileNonce] = useState(0)

  const resetTurnstile = () => {
    setTurnstileToken(null)
    setTurnstileNonce((n) => n + 1)
  }

  useEffect(() => {
    if (isAuthenticated) navigate('/dashboard')
  }, [isAuthenticated, navigate])

  useEffect(() => {
    publicApi.getConfig().then((c) => setTurnstileSiteKey(c.turnstile_site_key)).catch(() => {})
  }, [])

  const finishLogin = (data: LoginSuccess) => {
    login(data)
  }

  const handleOwnerLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    const formData = new FormData(e.currentTarget)
    try {
      const data = await authApi.loginOwner(
        formData.get('mc_number') as string, formData.get('password') as string, turnstileToken
      )
      if (isChallenge(data)) {
        setChallenge(data)
      } else {
        finishLogin(data)
      }
    } catch (err) {
      setError(errorMessage(err))
      resetTurnstile()
    } finally {
      setLoading(false)
    }
  }

  const handleDispatcherLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    const formData = new FormData(e.currentTarget)
    try {
      const data = await authApi.loginDispatcher(
        formData.get('username') as string, formData.get('password') as string, turnstileToken
      )
      if (isChallenge(data)) {
        setChallenge(data)
      } else {
        finishLogin(data)
      }
    } catch (err) {
      setError(errorMessage(err))
      resetTurnstile()
    } finally {
      setLoading(false)
    }
  }

  const selectMethod = async (m: string) => {
    setMethod(m)
    setCode('')
    setCodeSent(false)
    setError('')
    if (!challenge) return
    if (m === 'email' || m === 'sms' || m === 'telegram') {
      try {
        await twoFaApi.loginChallenge(m as 'email' | 'sms' | 'telegram', challenge.pending_token)
        setCodeSent(true)
      } catch (err) {
        setError(errorMessage(err))
      }
    }
  }

  // A fresh challenge auto-highlights its first method's tab, so it also
  // needs to actually run selectMethod for it - otherwise an email/SMS/
  // Telegram method (whichever comes first) never gets its code sent, and
  // the form sits on "Sending code..." forever until the user happens to
  // re-click the tab that already looks selected.
  useEffect(() => {
    if (challenge && challenge.methods.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      selectMethod(challenge.methods[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challenge])

  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!challenge) return
    setError('')
    setLoading(true)
    try {
      const data = await twoFaApi.loginVerify(challenge.pending_token, method, code)
      finishLogin(data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const useSecurityKey = async () => {
    if (!challenge) return
    setError('')
    setLoading(true)
    try {
      const { options } = await twoFaApi.loginWebauthnOptions(challenge.pending_token)
      const credentialJson = await getCredential(options)
      const data = await twoFaApi.loginWebauthnVerify(challenge.pending_token, credentialJson)
      finishLogin(data)
    } catch (err) {
      setError(errorMessage(err, 'Security key verification failed.'))
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
              <span className="logo-text">Freight Pilot</span>
            </Link>
            <h1 className="page-hero-title">Welcome Back</h1>
            <p className="page-hero-description">
              {challenge ? 'Verify it\u2019s you to finish logging in' : 'Log in to your dashboard'}
            </p>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          {!challenge ? (
            <>
              <div className="tabs">
                <button
                  className={`tab ${activeTab === 'owner' ? 'active-tab' : ''}`}
                  onClick={() => { setActiveTab('owner'); setError(''); resetTurnstile() }}
                >
                  Owner
                </button>
                <button
                  className={`tab ${activeTab === 'dispatcher' ? 'active-tab' : ''}`}
                  onClick={() => { setActiveTab('dispatcher'); setError(''); resetTurnstile() }}
                >
                  Dispatcher
                </button>
              </div>

              {activeTab === 'owner' ? (
                <form key="owner-login-form" onSubmit={handleOwnerLogin} className="card form">
                  <label>
                    <span>MC Number</span>
                    <input type="text" name="mc_number" placeholder="123456" required />
                  </label>
                  <label>
                    <span>Password</span>
                    <input type="password" name="password" placeholder="Password" required />
                  </label>
                  <p style={{ textAlign: 'right', margin: '-8px 0 0' }}>
                    <Link to="/forgot-password" style={{ color: 'var(--text-muted)', textDecoration: 'none', fontSize: '13px' }}>
                      Forgot password?
                    </Link>
                  </p>
                  <Turnstile key={turnstileNonce} siteKey={turnstileSiteKey} onToken={setTurnstileToken} />
                  <button
                    type="submit"
                    className="btn-primary btn-full"
                    disabled={loading || (!!turnstileSiteKey && !turnstileToken)}
                  >
                    {loading ? 'Logging in...' : 'Log in'}
                  </button>
                  {error && <p className="error">{error}</p>}
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>
                    Don't have an account?{' '}
                    <Link to="/register" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                      Register
                    </Link>
                  </p>
                </form>
              ) : (
                <form key="dispatcher-login-form" onSubmit={handleDispatcherLogin} className="card form">
                  <label>
                    <span>Username</span>
                    <input type="text" name="username" placeholder="Username" required />
                  </label>
                  <label>
                    <span>Password</span>
                    <input type="password" name="password" placeholder="Password" required />
                  </label>
                  <Turnstile key={turnstileNonce} siteKey={turnstileSiteKey} onToken={setTurnstileToken} />
                  <button
                    type="submit"
                    className="btn-primary btn-full"
                    disabled={loading || (!!turnstileSiteKey && !turnstileToken)}
                  >
                    {loading ? 'Logging in...' : 'Log in'}
                  </button>
                  {error && <p className="error">{error}</p>}
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>
                    Don't have a login? Ask your company's owner to create one from Settings → Dispatchers.
                  </p>
                </form>
              )}
            </>
          ) : (
            <div className="card form">
              <div className="method-tabs">
                {challenge.methods.map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={`method-tab ${method === m ? 'is-active' : ''}`}
                    onClick={() => selectMethod(m)}
                  >
                    {METHOD_LABELS[m] || m}
                  </button>
                ))}
                <button
                  type="button"
                  className={`method-tab ${method === 'recovery' ? 'is-active' : ''}`}
                  onClick={() => selectMethod('recovery')}
                >
                  Recovery code
                </button>
              </div>

              {method === 'webauthn' ? (
                <>
                  <p className="method-hint">
                    {isWebAuthnSupported()
                      ? 'Use your security key, Touch ID, or Windows Hello to continue.'
                      : 'This browser does not support security keys.'}
                  </p>
                  <button
                    type="button"
                    className="btn-primary btn-full"
                    onClick={useSecurityKey}
                    disabled={loading || !isWebAuthnSupported()}
                  >
                    {loading ? 'Verifying...' : 'Use security key'}
                  </button>
                </>
              ) : (
                <form onSubmit={submitCode}>
                  <label>
                    <span>
                      {method === 'totp'
                        ? 'Code from your authenticator app'
                        : method === 'recovery'
                        ? 'Recovery code'
                        : codeSent
                        ? `Code sent via ${METHOD_LABELS[method] || method}`
                        : 'Sending code...'}
                    </span>
                    <input
                      type="text"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      placeholder={method === 'recovery' ? 'XXXX-XXXX' : '123456'}
                      autoFocus
                      required
                    />
                  </label>
                  <button type="submit" className="btn-primary btn-full" disabled={loading || !code}>
                    {loading ? 'Verifying...' : 'Verify & log in'}
                  </button>
                </form>
              )}

              {error && <p className="error">{error}</p>}

              <button
                type="button"
                className="btn-ghost btn-full"
                onClick={() => { setChallenge(null); setError(''); setCode('') }}
              >
                ← Back to login
              </button>
            </div>
          )}

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
