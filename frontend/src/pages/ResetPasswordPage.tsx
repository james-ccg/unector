import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi, errorMessage } from '../services/api'
import PasswordInput from '../components/PasswordInput'
import './LoginPage.css'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const formData = new FormData(e.currentTarget)
    const newPassword = formData.get('new_password') as string
    const confirmPassword = formData.get('confirm_password') as string

    try {
      await authApi.resetPassword(token, newPassword, confirmPassword)
      setDone(true)
    } catch (err) {
      setError(errorMessage(err))
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
            <h1 className="page-hero-title">Set a New Password</h1>
          </div>
        </div>
      </section>

      <section className="auth-section">
        <div className="container" style={{ maxWidth: '500px' }}>
          {!token ? (
            <div className="card form">
              <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>Invalid reset link</p>
              <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
                This link is missing its reset token. Request a new one from the login page.
              </p>
              <Link to="/forgot-password" className="btn-primary btn-full" style={{ marginTop: 16, textAlign: 'center' }}>
                Request a new link
              </Link>
            </div>
          ) : done ? (
            <div className="card form">
              <p style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>Password updated</p>
              <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
                You can now log in with your new password.
              </p>
              <button className="btn-primary btn-full" style={{ marginTop: 16 }} onClick={() => navigate('/login')}>
                Go to login
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="card form">
              <label>
                <span>New Password</span>
                <PasswordInput name="new_password" placeholder="Min. 8 characters" required minLength={8} />
              </label>
              <label>
                <span>Confirm New Password</span>
                <PasswordInput name="confirm_password" placeholder="Repeat password" required minLength={8} />
              </label>
              <button type="submit" className="btn-primary btn-full" disabled={loading}>
                {loading ? 'Updating...' : 'Update Password'}
              </button>
              {error && <p className="error">{error}</p>}
              {error.toLowerCase().includes('expired') && (
                <p style={{ textAlign: 'center', margin: 0 }}>
                  <Link to="/forgot-password" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600, fontSize: '14px' }}>
                    Request a new reset link
                  </Link>
                </p>
              )}
            </form>
          )}
        </div>
      </section>
    </div>
  )
}
