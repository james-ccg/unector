import { Link } from 'react-router-dom'
import Icon from './Icon'
import './AppFooter.css'

export default function AppFooter() {
  return <footer className="app-footer"><div className="container app-footer-inner"><Link className="app-footer-brand" to="/dashboard"><span className="brand-mark">FP</span><span>Freight Pilot</span></Link><p>Operations workspace for modern carriers.</p><nav aria-label="Footer navigation"><Link to="/settings">Settings</Link><Link to="/pages/security">Security</Link><Link to="/pages/faq">Support <Icon name="chevron-right" size={14} /></Link></nav><span className="app-footer-copy">© 2026 Freight Pilot</span></div></footer>
}
