import React, { createContext, useContext, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

interface User {
  token: string
  role: 'owner' | 'dispatcher'
  companyName?: string
  companyId?: number
}

interface AuthContextType {
  user: User | null
  login: (token: string, role: 'owner' | 'dispatcher', companyName?: string, companyId?: number) => void
  logout: () => void
  isAuthenticated: boolean
  isLoading: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    // Check for existing session on mount
    const token = localStorage.getItem('fp_token')
    const role = localStorage.getItem('fp_role') as 'owner' | 'dispatcher' | null
    const companyName = localStorage.getItem('fp_company') || undefined
    const companyId = localStorage.getItem('fp_company_id')
      ? parseInt(localStorage.getItem('fp_company_id')!)
      : undefined

    if (token && role) {
      setUser({ token, role, companyName, companyId })
    }
    setIsLoading(false)
  }, [])

  const login = (token: string, role: 'owner' | 'dispatcher', companyName?: string, companyId?: number) => {
    // Save to localStorage
    localStorage.setItem('fp_token', token)
    localStorage.setItem('fp_role', role)
    if (companyName) {
      localStorage.setItem('fp_company', companyName)
    }
    if (companyId) {
      localStorage.setItem('fp_company_id', companyId.toString())
    }
    
    // Update state - this will trigger re-render and persist session
    setUser({ token, role, companyName, companyId })
  }

  const logout = () => {
    localStorage.removeItem('fp_token')
    localStorage.removeItem('fp_role')
    localStorage.removeItem('fp_company')
    localStorage.removeItem('fp_company_id')
    setUser(null)
    navigate('/login')
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user, isLoading }}>
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
