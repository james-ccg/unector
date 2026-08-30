import { Link, useLocation } from 'react-router-dom'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import { useAuth } from '../context/AuthContext'
import './NotFoundPage.css'

/** Catch-all for any URL the router doesn't recognise.
 *
 * Without this, an unknown path matched no route and rendered a blank white
 * page - no header, no footer, no way back. A 404 is most often a typo or a
 * stale link, so the job here is to say plainly what happened and offer the
 * handful of places someone was probably trying to reach. */
export default function NotFoundPage() {
  const { pathname } = useLocation()
  const { isAuthenticated } = useAuth()

  return (
    <Layout>
      <div className="notfound">
        <div className="container notfound-inner">
          <p className="notfound-code">404</p>
          <h1 className="notfound-title">We can&apos;t find that page</h1>
          <p className="notfound-text">
            Nothing lives at <code className="notfound-path">{pathname}</code>. It may have been
            moved, or the link that brought you here might be out of date.
          </p>

          <div className="notfound-actions">
            <Link to={isAuthenticated ? '/dashboard' : '/'} className="btn-primary">
              {isAuthenticated ? 'Back to dashboard' : 'Back to home'}
            </Link>
            <Link to="/pages/faq" className="btn-secondary">
              Read the FAQ
            </Link>
          </div>

          <div className="notfound-links">
            <p className="notfound-links-label">Or try one of these</p>
            <ul>
              {isAuthenticated ? (
                <>
                  <li><Link to="/dashboard"><Icon name="truck" size={15} /> Dashboard</Link></li>
                  <li><Link to="/monitoring"><Icon name="location" size={15} /> Live GPS</Link></li>
                  <li><Link to="/settings"><Icon name="settings" size={15} /> Settings</Link></li>
                </>
              ) : (
                <>
                  <li><Link to="/pages/pricing"><Icon name="money" size={15} /> Pricing</Link></li>
                  <li><Link to="/login"><Icon name="logout" size={15} /> Log in</Link></li>
                  <li><Link to="/pages/security"><Icon name="shield" size={15} /> Security</Link></li>
                </>
              )}
            </ul>
          </div>
        </div>
      </div>
    </Layout>
  )
}
