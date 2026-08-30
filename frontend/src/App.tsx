import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { PreferencesProvider } from './context/PreferencesContext'
import PrivateRoute from './components/PrivateRoute'
import ScrollToHash from './components/ScrollToHash'
import RequireGmailConnected from './components/RequireGmailConnected'
import HomePage from './pages/HomePage'

// Route-based code splitting: the marketing pages (Home, Pricing, FAQ...)
// shouldn't have to download the dashboard's chart library (recharts) or
// any other page's own dependencies just to render. HomePage stays eager
// since it's the most common landing page and shouldn't show a loading
// flash on first paint.
const LoginPage = lazy(() => import('./pages/LoginPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('./pages/ResetPasswordPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const MonitoringPage = lazy(() => import('./pages/MonitoringPage'))
const OnboardingGmailPage = lazy(() => import('./pages/OnboardingGmailPage'))
const FAQPage = lazy(() => import('./pages/FAQPage'))
const PricingPage = lazy(() => import('./pages/PricingPage'))
const SecurityPage = lazy(() => import('./pages/SecurityPage'))
const TrustPage = lazy(() => import('./pages/TrustPage'))
const UpdatesPage = lazy(() => import('./pages/UpdatesPage'))
const PrivacyPolicyPage = lazy(() => import('./pages/PrivacyPolicyPage'))
const TermsOfServicePage = lazy(() => import('./pages/TermsOfServicePage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))

function RouteFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
      <div className="spinner" />
    </div>
  )
}

function App() {
  return (
    <ThemeProvider>
      <PreferencesProvider>
      <AuthProvider>
        <ScrollToHash />
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/pages/faq" element={<FAQPage />} />
            <Route path="/pages/pricing" element={<PricingPage />} />
            <Route path="/pages/security" element={<SecurityPage />} />
            <Route path="/pages/trust" element={<TrustPage />} />
            <Route path="/pages/updates" element={<UpdatesPage />} />
            <Route path="/pages/privacy" element={<PrivacyPolicyPage />} />
            <Route path="/pages/terms" element={<TermsOfServicePage />} />
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
            {/* Must stay last: "*" matches anything the routes above didn't.
                Without it an unknown URL rendered a blank page. */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </AuthProvider>
      </PreferencesProvider>
    </ThemeProvider>
  )
}

export default App
