import { Lock, KeyRound, ShieldCheck, ShieldHalf, Eye, Search } from 'lucide-react'
import Layout from '../components/Layout'

export default function SecurityPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title"><Lock size={36} /> Security & Privacy</h1>
            <p className="page-description">
              Your data security is our top priority. Here's how we protect your business.
            </p>
          </div>

          <div className="content-grid">
            <div className="content-card card">
              <div className="content-icon"><KeyRound size={24} /></div>
              <h3 className="content-title">Encrypted in Transit</h3>
              <p className="content-text">
                All data between your devices and our servers travels over HTTPS/TLS -
                nothing is ever sent in the clear.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon"><Lock size={24} /></div>
              <h3 className="content-title">OAuth 2.0 Authentication</h3>
              <p className="content-text">
                Gmail integration uses secure OAuth 2.0. We never store your email password.
                You can revoke access anytime from your Google account.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon"><ShieldCheck size={24} /></div>
              <h3 className="content-title">Encrypted Credential Storage</h3>
              <p className="content-text">
                Every connected integration's credentials are encrypted at rest, never stored
                or logged in plain text.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon"><ShieldHalf size={24} /></div>
              <h3 className="content-title">Two-Factor Authentication</h3>
              <p className="content-text">
                Authenticator app, security keys (Touch ID, Windows Hello, YubiKey), email,
                SMS, or Telegram - protect your login with a second factor, plus one-time
                backup recovery codes.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon"><Eye size={24} /></div>
              <h3 className="content-title">Privacy First</h3>
              <p className="content-text">
                We only access data necessary for service functionality. No selling of data to
                third parties. Ever.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon"><Search size={24} /></div>
              <h3 className="content-title">Audited Dependencies</h3>
              <p className="content-text">
                Every backend and frontend dependency has been checked with pip-audit and
                npm audit for known vulnerabilities, with fixes applied where available -
                and we re-run these checks before major releases.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
