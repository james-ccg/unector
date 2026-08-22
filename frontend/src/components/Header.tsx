import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Icon from './Icon'
import './Header.css'

interface HeaderProps {
  transparent?: boolean
}

export default function Header({ transparent = false }: HeaderProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isScrolled, setIsScrolled] = useState(false)
  const { isAuthenticated, user } = useAuth()

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20)
    }

    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const headerClass = `header ${transparent && !isScrolled ? 'header-transparent' : ''} ${
    isScrolled ? 'header-scrolled' : ''
  }`

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
            <Link to="/dashboard" className="nav-profile" onClick={() => setIsMenuOpen(false)}>
              <span className="nav-profile-avatar">
                {(user?.companyName || 'FP').slice(0, 2).toUpperCase()}
              </span>
              <span className="nav-profile-label">Profile</span>
            </Link>
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
    </header>
  )
}
