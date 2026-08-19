import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import RequireGmailConnected from './components/RequireGmailConnected'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import SettingsPage from './pages/SettingsPage'
import MonitoringPage from './pages/MonitoringPage'
import OnboardingGmailPage from './pages/OnboardingGmailPage'
import FAQPage from './pages/FAQPage'
import PricingPage from './pages/PricingPage'
import SecurityPage from './pages/SecurityPage'
import TrustPage from './pages/TrustPage'
import UpdatesPage from './pages/UpdatesPage'

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/pages/faq" element={<FAQPage />} />
        <Route path="/pages/pricing" element={<PricingPage />} />
        <Route path="/pages/security" element={<SecurityPage />} />
        <Route path="/pages/trust" element={<TrustPage />} />
        <Route path="/pages/updates" element={<UpdatesPage />} />
        <Route
          path="/onboarding/connect-gmail"
          element={
            <PrivateRoute>
              <OnboardingGmailPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/dashboard"
          element={
            <PrivateRoute>
              <RequireGmailConnected>
                <DashboardPage />
              </RequireGmailConnected>
            </PrivateRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <PrivateRoute>
              <SettingsPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/monitoring"
          element={
            <PrivateRoute>
              <RequireGmailConnected>
                <MonitoringPage />
              </RequireGmailConnected>
            </PrivateRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}

export default App
