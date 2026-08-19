import Layout from '../components/Layout'

export default function SecurityPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">🔒 Security & Privacy</h1>
            <p className="page-description">
              Your data security is our top priority. Here's how we protect your business.
            </p>
          </div>

          <div className="content-grid">
            <div className="content-card card">
              <div className="content-icon">🔐</div>
              <h3 className="content-title">End-to-End Encryption</h3>
              <p className="content-text">
                All data transmitted between your devices and our servers is encrypted using
                industry-standard TLS 1.3 protocol.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon">🔑</div>
              <h3 className="content-title">OAuth 2.0 Authentication</h3>
              <p className="content-text">
                Gmail integration uses secure OAuth 2.0. We never store your email password.
                You can revoke access anytime from your Google account.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon">🛡️</div>
              <h3 className="content-title">SOC 2 Compliant</h3>
              <p className="content-text">
                Our infrastructure meets SOC 2 Type II compliance standards for security,
                availability, and confidentiality.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon">💾</div>
              <h3 className="content-title">Regular Backups</h3>
              <p className="content-text">
                Automated daily backups with point-in-time recovery. Your data is replicated
                across multiple secure data centers.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon">👁️</div>
              <h3 className="content-title">Privacy First</h3>
              <p className="content-text">
                We only access data necessary for service functionality. No selling of data to
                third parties. Ever.
              </p>
            </div>

            <div className="content-card card">
              <div className="content-icon">🔍</div>
              <h3 className="content-title">Regular Security Audits</h3>
              <p className="content-text">
                Third-party penetration testing and security audits performed quarterly to
                identify and fix vulnerabilities.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
