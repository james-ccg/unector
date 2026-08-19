import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Gmail is a mandatory part of onboarding for owners - the bot's core
// feature (pulling rate confirmations from email) depends on it. Wrap
// this around pages that need it (Dashboard, Monitoring) but not Settings
// itself, since that's where an owner reconnects if they ever disconnect.
// Dispatchers pass through unconditionally - they can't manage
// integrations themselves, so gating them would strand them with no way
// to fix it.
export default function RequireGmailConnected({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()

  if (user?.role === 'owner' && user.gmailConnected === false) {
    return <Navigate to="/onboarding/connect-gmail" replace />
  }

  return <>{children}</>
}
