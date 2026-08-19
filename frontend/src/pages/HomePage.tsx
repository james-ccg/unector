import Layout from '../components/Layout'
import './HomePage.css'

export default function HomePage() {
  return (
    <Layout transparentHeader>
      <section className="hero">
        <div className="hero-container container">
          <div className="hero-content">
            <div className="hero-badge">
              <span>⚡</span>
              <span>AI-Powered Dispatch Automation</span>
            </div>
            <h1 className="hero-title">
              Smart Dispatch Management for
              <span className="gradient-text"> Modern Trucking</span>
            </h1>
            <p className="hero-description">
              Automate load management, track drivers in real-time, and streamline communication
              with brokers. Freight Pilot brings intelligence to your dispatch operations through
              Telegram.
            </p>
            <div className="hero-buttons">
              <a href="/register" className="btn-primary btn-lg">
                <span>Start Free Trial</span>
                <span>→</span>
              </a>
              <a href="#features" className="btn-secondary btn-lg">
                <span>See Features</span>
              </a>
            </div>
          </div>
        </div>
      </section>

      <section className="features-section" id="features">
        <div className="container">
          <div className="section-header">
            <h2 className="section-title">Everything You Need to Run Your Fleet</h2>
            <p className="section-description">
              Powerful features designed for modern trucking operations
            </p>
          </div>
          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon">🤖</div>
              <h3 className="feature-title">AI Load Extraction</h3>
              <p className="feature-description">
                Google Gemini AI automatically extracts load details from rate confirmations
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📧</div>
              <h3 className="feature-title">Gmail Integration</h3>
              <p className="feature-description">
                Connect your Gmail via OAuth 2.0 - bot monitors and processes emails automatically
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🗺️</div>
              <h3 className="feature-title">GPS Tracking</h3>
              <p className="feature-description">
                Samsara integration with real-time location tracking and auto-notifications
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📱</div>
              <h3 className="feature-title">Telegram Bot</h3>
              <p className="feature-description">
                Drivers get loads via Telegram - simple, familiar, and always accessible
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📊</div>
              <h3 className="feature-title">Smart Dashboard</h3>
              <p className="feature-description">
                Track drivers, loads, and earnings in real-time from any device
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">👥</div>
              <h3 className="feature-title">Multi-Dispatcher</h3>
              <p className="feature-description">
                Add unlimited dispatchers - each with their own secure login
              </p>
            </div>
          </div>
        </div>
      </section>
    </Layout>
  )
}
