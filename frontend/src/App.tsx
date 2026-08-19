import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import SettingsPage from './pages/SettingsPage'
import MonitoringPage from './pages/MonitoringPage'
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
          path="/dashboard"
          element={
            <PrivateRoute>
              <DashboardPage />
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
              <MonitoringPage />
            </PrivateRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}

export default App
