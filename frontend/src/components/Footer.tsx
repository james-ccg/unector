import { Link } from 'react-router-dom'
import './Footer.css'

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-grid">
          <div className="footer-column footer-brand">
            <div className="footer-logo">
              <div className="logo-icon">FP</div>
              <span className="logo-text">Freight Pilot</span>
            </div>
            <p className="footer-description">
              Smart dispatch management for modern trucking companies. Automate your operations
              with AI-powered tools.
            </p>
            <div className="social-links">
              <a href="#" className="social-link" aria-label="Telegram">
                📱
              </a>
              <a href="#" className="social-link" aria-label="Twitter">
                🐦
              </a>
              <a href="#" className="social-link" aria-label="LinkedIn">
                💼
              </a>
            </div>
          </div>

          <div className="footer-column">
            <h4 className="footer-title">Product</h4>
            <ul className="footer-links">
              <li>
                <a href="/#features">Features</a>
              </li>
              <li>
                <Link to="/pages/pricing">Pricing</Link>
              </li>
              <li>
                <Link to="/pages/updates">Updates</Link>
              </li>
              <li>
                <Link to="/pages/security">Security</Link>
              </li>
            </ul>
          </div>

          <div className="footer-column">
            <h4 className="footer-title">Resources</h4>
            <ul className="footer-links">
              <li>
                <Link to="/pages/faq">FAQ</Link>
              </li>
              <li>
                <Link to="/pages/trust">Trust & Stats</Link>
              </li>
              <li>
                <a href="#support">Support</a>
              </li>
            </ul>
          </div>

          <div className="footer-column">
            <h4 className="footer-title">Legal</h4>
            <ul className="footer-links">
              <li>
                <a href="#privacy">Privacy Policy</a>
              </li>
              <li>
                <a href="#terms">Terms of Service</a>
              </li>
            </ul>
          </div>
        </div>

        <div className="footer-bottom">
          <p className="copyright">© 2026 Freight Pilot. All rights reserved.</p>
        </div>
      </div>
    </footer>
  )
}
