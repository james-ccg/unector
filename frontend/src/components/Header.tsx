import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Icon from './Icon'
import EditStatusModal from './EditStatusModal'
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

  return (
    <header className={headerClass} id="header">
      <nav className="nav container">
        <Link to="/" className="nav-logo">
          <div className="logo-icon">FP</div>
          <span className="logo-text">Freight Pilot</span>
        </Link>

        <div className={`nav-menu ${isMenuOpen ? 'show-menu' : ''}`} id="nav-menu">
          <ul className="nav-list">
            <li className="nav-item">
              <Link to="/" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Home
              </Link>
            </li>
            <li className="nav-item">
              <a href="/#features" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Features
              </a>
            </li>
            <li className="nav-item">
              <Link to="/pages/pricing" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Pricing
              </Link>
            </li>
            <li className="nav-item">
              <Link to="/pages/trust" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Trust & Stats
              </Link>
            </li>
            <li className="nav-item">
              <Link to="/pages/faq" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                FAQ
              </Link>
            </li>
            <li className="nav-item">
              <Link to="/pages/updates" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Updates
              </Link>
            </li>
            <li className="nav-item">
              <Link to="/pages/security" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                Security
              </Link>
            </li>
            {isAuthenticated && (
              <li className="nav-item nav-item-mobile-only">
                <Link to="/monitoring" className="nav-link" onClick={() => setIsMenuOpen(false)}>
                  Live GPS
                </Link>
              </li>
            )}
          </ul>
          <button type="button" className="nav-close" aria-label="Close menu" onClick={() => setIsMenuOpen(false)}>
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="nav-actions">
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
                  <button
                    type="button"
                    className="nav-profile-menu-item"
                    onClick={() => {
                      setStatusModalOpen(true)
                      setIsProfileMenuOpen(false)
                    }}
                  >
                    <Icon name="check" size={16} /> Set Status
                  </button>
                  <Link
                    to="/monitoring"
                    className="nav-profile-menu-item"
                    onClick={() => {
                      setIsProfileMenuOpen(false)
                      setIsMenuOpen(false)
                    }}
                  >
                    <Icon name="location" size={16} /> Live GPS
                  </Link>
                  <Link
                    to="/settings"
                    className="nav-profile-menu-item"
                    onClick={() => {
                      setIsProfileMenuOpen(false)
                      setIsMenuOpen(false)
                    }}
                  >
                    <Icon name="settings" size={16} /> Settings
                  </Link>
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
