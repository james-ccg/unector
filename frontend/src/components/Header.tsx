import { useState, useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Icon from './Icon'
import EditStatusModal from './EditStatusModal'
import NotificationBell from './NotificationBell'
import './Header.css'

interface HeaderProps {
  transparent?: boolean
}

export default function Header({ transparent = false }: HeaderProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isScrolled, setIsScrolled] = useState(false)
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false)
  const [statusModalOpen, setStatusModalOpen] = useState(false)
  const { isAuthenticated, user, logout } = useAuth()
  const profileMenuRef = useRef<HTMLDivElement>(null)
  const location = useLocation()

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20)
    }

    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (!isProfileMenuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setIsProfileMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isProfileMenuOpen])

  const headerClass = `header ${transparent && !isScrolled ? 'header-transparent' : ''} ${
    isScrolled ? 'header-scrolled' : ''
  }`

  const displayName = user?.role === 'owner' ? user?.companyName : user?.username

  const closeMenus = () => {
    setIsMenuOpen(false)
    setIsProfileMenuOpen(false)
  }

  // Which nav to show follows the ROUTE, not whether someone is signed in.
  // Keying it off auth meant a signed-in owner standing on the marketing
  // site lost Pricing entirely - exactly the person most likely to want it,
  // since that's where plan upgrades start.
  const APP_ROUTES = ['/dashboard', '/monitoring', '/settings', '/onboarding']
  const isAppRoute = APP_ROUTES.some((route) => location.pathname.startsWith(route))

  // Four items either way - inside the 5-7 a top nav can carry before it
  // starts reading as a wall of links.
  const NAV_ITEMS: { to: string; label: string }[] = isAppRoute
    ? [
        { to: '/dashboard', label: 'Dashboard' },
        { to: '/monitoring', label: 'Live GPS' },
        { to: '/settings', label: 'Settings' },
      ]
    : [
        // No "Home" - the logo to its left already is the home link, and
        // repeating it is the classic wasted nav slot.
        // A router Link, not a plain <a>: an <a> would reload the whole SPA
        // just to move down one page. ScrollToHash handles the #features.
        { to: '/#features', label: 'Features' },
        { to: '/pages/pricing', label: 'Pricing' },
        { to: '/pages/faq', label: 'FAQ' },
        { to: '/pages/security', label: 'Security' },
      ]

  return (
    <header className={headerClass} id="header">
      <nav className="nav container">
        <Link to="/" className="nav-logo">
          <span className="logo-icon" role="presentation" />
          <span className="logo-text">Freight Pilot</span>
        </Link>

        <div className={`nav-menu ${isMenuOpen ? 'show-menu' : ''}`} id="nav-menu">
          <ul className="nav-list">
            {/* Signed in, the header is the APP's navigation - a dispatcher
                looking at live loads has no use for Pricing or FAQ, and
                showing seven marketing links there was the main reason the
                menus read as cluttered. Signed out it's the marketing site.
                Trust & Stats and Updates aren't lost either way: the footer
                links both. */}
            {NAV_ITEMS.map((item) => (
              <li className="nav-item" key={item.to}>
                <Link
                  to={item.to}
                  className={`nav-link ${location.pathname === item.to ? 'is-current' : ''}`}
                  onClick={closeMenus}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
          <button type="button" className="nav-close" aria-label="Close menu" onClick={() => setIsMenuOpen(false)}>
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="nav-actions">
          {isAuthenticated && <NotificationBell />}
          {isAuthenticated ? (
            <div className="nav-profile-wrap" ref={profileMenuRef}>
              <button
                type="button"
                className="nav-profile"
                onClick={() => setIsProfileMenuOpen((open) => !open)}
                aria-expanded={isProfileMenuOpen}
              >
                <span className="nav-profile-avatar">
                  {user?.avatar ? (
                    <img src={user.avatar} alt="" className="nav-profile-avatar-img" />
                  ) : (
                    user?.status?.emoji || (displayName || 'FP').slice(0, 2).toUpperCase()
                  )}
                </span>
                <span className="nav-profile-label">{user?.status?.text || displayName || 'Profile'}</span>
              </button>
              {isProfileMenuOpen && (
                <div className="nav-profile-menu">
                  {/* On the marketing pages the main nav is marketing links,
                      so this is the way back into the app. On the app's own
                      pages Dashboard is already the first nav item, and
                      repeating it here would put the same destination on one
                      screen twice. */}
                  {!isAppRoute && (
                    <Link to="/dashboard" className="nav-profile-menu-item" onClick={closeMenus}>
                      <Icon name="truck" size={16} /> Dashboard
                    </Link>
                  )}
                  <button
                    type="button"
                    className="nav-profile-menu-item"
                    onClick={() => {
                      setStatusModalOpen(true)
                      setIsProfileMenuOpen(false)
                    }}
                  >
                    <Icon name="check" size={16} /> Set status
                  </button>
                  <button
                    type="button"
                    className="nav-profile-menu-item is-danger"
                    onClick={() => {
                      setIsProfileMenuOpen(false)
                      logout()
                    }}
                  >
                    <Icon name="logout" size={16} /> Sign out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <Link to="/login" className="btn-secondary">
                Login
              </Link>
              <Link to="/register" className="btn-primary">
                Get Started
              </Link>
            </>
          )}
          <button
            type="button"
            className="nav-toggle"
            aria-label={isMenuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={isMenuOpen}
            onClick={() => setIsMenuOpen(!isMenuOpen)}
          >
            <Icon name="menu" size={22} />
          </button>
        </div>
      </nav>
      {statusModalOpen && <EditStatusModal onClose={() => setStatusModalOpen(false)} />}
    </header>
  )
}
