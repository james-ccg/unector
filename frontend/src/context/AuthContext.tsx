import React, { createContext, useContext, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi, type LoginSuccess } from '../services/api'

interface User {
  role: 'owner' | 'dispatcher'
  companyName?: string
  companyId?: number
  dispatcherId?: number
  // undefined for dispatchers (not applicable); boolean for owners.
  gmailConnected?: boolean
}

interface AuthContextType {
  user: User | null
  login: (session: LoginSuccess) => void
  logout: () => void
  refreshUser: () => Promise<void>
  isAuthenticated: boolean
  isLoading: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

function toUser(session: LoginSuccess): User {
  return {
    role: session.role,
    companyName: session.company_name,
    companyId: session.company_id,
    dispatcherId: session.dispatcher_id,
    gmailConnected: session.gmail_connected,
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    // The session lives in an httpOnly cookie the frontend can't read directly,
    // so restoring it on load means asking the backend whether it's still valid.
    authApi
      .me()
      .then((session) => setUser(toUser(session)))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false))
  }, [])

  const login = (session: LoginSuccess) => {
    // The session/CSRF cookies are already set by the browser from the
    // login/register response - this just updates UI state.
    setUser(toUser(session))
  }

  const logout = () => {
    authApi.logout().finally(() => {
      setUser(null)
      navigate('/login')
    })
  }

  // Re-checks the session with the backend - used after an action that
  // changes server-side state the frontend doesn't otherwise learn about,
  // like completing the mandatory Gmail connect step.
  const refreshUser = async () => {
    try {
      const session = await authApi.me()
      setUser(toUser(session))
    } catch {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, refreshUser, isAuthenticated: !!user, isLoading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
