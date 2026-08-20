import { Link } from 'react-router-dom'
import { Send, AtSign, Briefcase } from 'lucide-react'
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
              <a
                href="https://t.me/Freight_Pilot"
                className="social-link"
                aria-label="Telegram channel"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Send size={18} />
              </a>
              <span className="social-link is-disabled" aria-label="Twitter" title="Coming soon">
                <AtSign size={18} />
              </span>
              <span className="social-link is-disabled" aria-label="LinkedIn" title="Coming soon">
                <Briefcase size={18} />
              </span>
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
            </ul>
          </div>

          <div className="footer-column">
            <h4 className="footer-title">Legal</h4>
            <ul className="footer-links">
              <li>
                <span className="is-disabled" title="Coming soon">Privacy Policy</span>
              </li>
              <li>
                <span className="is-disabled" title="Coming soon">Terms of Service</span>
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
