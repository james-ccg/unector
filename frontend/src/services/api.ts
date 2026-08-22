// API service for backend communication
const API_BASE = ''

const CSRF_COOKIE_NAME = 'fp_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

type ApiOptions = RequestInit

/** Extracts a human-readable message from something caught in a try/catch.
 * apiRequest below always throws a real Error, but a catch clause's variable
 * is typed unknown (TS can't statically know what a call site threw), so
 * this is the one place that assumption lives. */
export function errorMessage(err: unknown, fallback = 'Something went wrong.'): string {
  return err instanceof Error && err.message ? err.message : fallback
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

export async function apiRequest<T>(
  path: string,
  options: ApiOptions = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (options.headers) {
    Object.entries(options.headers).forEach(([key, value]) => {
      headers[key] = String(value)
    })
  }

  // The session lives in an httpOnly cookie the browser attaches automatically
  // (credentials: 'include'). State-changing requests also need the matching
  // CSRF header - see miniapp/auth.py's module docstring for the full pattern.
  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    const csrfToken = readCookie(CSRF_COOKIE_NAME)
    if (csrfToken) {
      headers[CSRF_HEADER_NAME] = csrfToken
    }
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)

  try {
    const response = await fetch(API_BASE + path, {
      ...options,
      headers,
      credentials: 'include',
      signal: controller.signal,
    })

    clearTimeout(timeout)

    let data: unknown = {}
    const contentType = response.headers.get('content-type')
    if (contentType?.includes('application/json')) {
      try {
        data = await response.json()
      } catch (e) {
        console.error('Failed to parse JSON response:', e)
      }
    }

    if (!response.ok) {
      const body = asRecord(data)
      let errorMsg = (body.detail as string) || (body.message as string) || 'Request failed'

      // A 401 from a login/register/2FA-challenge call just means THAT
      // attempt was rejected (wrong password, wrong code, ...) - there was
      // no prior session to "expire". Only an authenticated call failing
      // with 401 actually means the session lapsed.
      const isLoginAttempt = path.startsWith('/api/auth/') || path.startsWith('/api/2fa/login/')

      switch (response.status) {
        case 401:
          if (!isLoginAttempt) {
            errorMsg = 'Session expired. Please log in again.'
            // Lets AuthContext clear its stale user state and redirect - it
            // ignores this while already logged out (e.g. the routine
            // session check on a public page), so no redirect loop.
            window.dispatchEvent(new Event('fp:session-expired'))
          }
          break
        case 403:
          errorMsg = (body.detail as string) || 'Access denied'
          break
        case 404:
          errorMsg = 'Resource not found'
          break
        case 500:
          errorMsg = 'Server error. Please try again later.'
          break
        case 503:
          errorMsg = 'Service temporarily unavailable'
          break
      }

      throw new Error(errorMsg)
    }

    return data as T
  } catch (err: unknown) {
    clearTimeout(timeout)

    if ((err instanceof DOMException || err instanceof Error) && err.name === 'AbortError') {
      throw new Error('Request timeout. Please check your connection.', { cause: err })
    }

    if (!navigator.onLine) {
      throw new Error('No internet connection', { cause: err })
    }

    throw err
  }
}

export interface TwoFaChallenge {
  requires_2fa: true
  pending_token: string
  methods: ('totp' | 'email' | 'sms' | 'telegram' | 'webauthn')[]
}

export interface LoginSuccess {
  role: 'owner' | 'dispatcher'
  company_name?: string
  company_id: number
  dispatcher_id?: number
  // Only present for owners - Gmail connection is mandatory for them (the
  // bot's core feature depends on it), not applicable to dispatchers.
  gmail_connected?: boolean
}

export const authApi = {
  loginOwner: (mcNumber: string, password: string, turnstileToken?: string | null) =>
    apiRequest<LoginSuccess | TwoFaChallenge>('/api/auth/owner', {
      method: 'POST',
      body: JSON.stringify({ mc_number: mcNumber, password, turnstile_token: turnstileToken }),
    }),

  loginDispatcher: (username: string, password: string, turnstileToken?: string | null) =>
    apiRequest<LoginSuccess | TwoFaChallenge>('/api/auth/dispatcher', {
      method: 'POST',
      body: JSON.stringify({ username, password, turnstile_token: turnstileToken }),
    }),

  register: (data: {
    mc_number: string
    company_name: string
    email: string
    password: string
    confirm_password: string
    turnstile_token?: string | null
    pending_token?: string | null
  }) =>
    apiRequest<LoginSuccess>(
      '/api/auth/register',
      { method: 'POST', body: JSON.stringify(data) }
    ),

  // Gmail-first registration - connect Gmail before any account exists,
  // confirm you own that inbox, then register() above (with pending_token)
  // actually creates the company. See PendingRegistration's docstring.
  registerGmailStart: () =>
    apiRequest<{ auth_url: string }>('/api/auth/register/gmail/start'),

  registerPendingStatus: (pendingToken: string) =>
    apiRequest<{ gmail_email: string; email_verified: boolean }>(
      `/api/auth/register/pending-status?pending_token=${encodeURIComponent(pendingToken)}`
    ),

  registerVerifyCode: (pendingToken: string, code: string) =>
    apiRequest<{ verified: boolean }>('/api/auth/register/verify-code', {
      method: 'POST',
      body: JSON.stringify({ pending_token: pendingToken, code }),
    }),

  registerResendVerification: (pendingToken: string) =>
    apiRequest<{ success: boolean }>('/api/auth/register/resend-verification', {
      method: 'POST',
      body: JSON.stringify({ pending_token: pendingToken }),
    }),

  logout: () => apiRequest<{ success: boolean }>('/api/auth/logout', { method: 'POST' }),

  forgotPassword: (mcNumber: string, turnstileToken?: string | null) =>
    apiRequest<{ message: string }>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ mc_number: mcNumber, turnstile_token: turnstileToken }),
    }),

  resetPassword: (token: string, newPassword: string, confirmPassword: string) =>
    apiRequest<{ success: boolean }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword, confirm_password: confirmPassword }),
    }),

  // Called on app load to check whether the httpOnly session cookie (if any)
  // is still valid - the frontend never sees the token itself, only this result.
  me: () => apiRequest<LoginSuccess>('/api/me'),
}

export interface TwoFaStatus {
  totp_enabled: boolean
  email_otp_enabled: boolean
  contact_email: string | null
  sms_otp_enabled: boolean
  phone_number: string | null
  telegram_otp_enabled: boolean
  telegram_linked: boolean
  webauthn_count: number
  recovery_codes_remaining: number
  any_enabled: boolean
}

export const twoFaApi = {
  // ---- while already logged in: Settings > Security ----
  getStatus: () =>
    apiRequest<TwoFaStatus>('/api/2fa/status'),

  totpSetup: () =>
    apiRequest<{ secret: string; qr_code: string }>('/api/2fa/totp/setup', { method: 'POST' }),
  totpVerify: (code: string) =>
    apiRequest<{ enabled: boolean }>('/api/2fa/totp/verify', {
      method: 'POST',
      body: JSON.stringify({ channel: 'totp', code }),
    }),
  totpDisable: () =>
    apiRequest<{ enabled: boolean }>('/api/2fa/totp', { method: 'DELETE' }),

  otpSend: (channel: 'email' | 'sms' | 'telegram', contact: string | null) =>
    apiRequest<{ sent: boolean }>('/api/2fa/otp/send', {
      method: 'POST',
      body: JSON.stringify({ channel, contact }),
    }),
  otpConfirm: (channel: 'email' | 'sms' | 'telegram', code: string, contact: string | null) =>
    apiRequest<{ enabled: boolean }>(`/api/2fa/otp/confirm?contact=${encodeURIComponent(contact || '')}`, {
      method: 'POST',
      body: JSON.stringify({ channel, code }),
    }),
  otpDisable: (channel: 'email' | 'sms' | 'telegram') =>
    apiRequest<{ enabled: boolean }>(`/api/2fa/otp/${channel}`, { method: 'DELETE' }),

  telegramLinkStart: () =>
    apiRequest<{ code: string; bot_command: string }>('/api/2fa/telegram/link/start', { method: 'POST' }),

  webauthnList: () =>
    apiRequest<{ id: number; label: string | null; created_at: string | null }[]>('/api/2fa/webauthn'),

  webauthnRegisterOptions: () =>
    apiRequest<{ options: string }>('/api/2fa/webauthn/register/options', {
      method: 'POST',
    }),
  webauthnRegisterVerify: (credentialJson: string, label: string) =>
    apiRequest<{ registered: boolean }>('/api/2fa/webauthn/register/verify', {
      method: 'POST',
      body: JSON.stringify({ credential_json: credentialJson, label }),
    }),
  webauthnDelete: (credentialPk: number) =>
    apiRequest<{ deleted: boolean }>(`/api/2fa/webauthn/${credentialPk}`, { method: 'DELETE' }),

  recoveryCodesGenerate: () =>
    apiRequest<{ codes: string[] }>('/api/2fa/recovery-codes/generate', { method: 'POST' }),

  // ---- during login, before the session cookie exists: the frontend holds
  // the short-lived pending_token itself and passes it as a bearer header,
  // since no session cookie exists yet at this point ----
  loginChallenge: (channel: 'email' | 'sms' | 'telegram', pendingToken: string) =>
    apiRequest<{ sent: boolean }>('/api/2fa/login/challenge', {
      method: 'POST',
      body: JSON.stringify({ channel }),
      headers: { Authorization: `Bearer ${pendingToken}` },
    }),
  loginVerify: (pendingToken: string, method: string, code: string) =>
    apiRequest<LoginSuccess>('/api/2fa/login/verify', {
      method: 'POST',
      body: JSON.stringify({ pending_token: pendingToken, method, code }),
    }),
  loginWebauthnOptions: (pendingToken: string) =>
    apiRequest<{ options: string }>('/api/2fa/login/webauthn/options', {
      method: 'POST',
      headers: { Authorization: `Bearer ${pendingToken}` },
    }),
  loginWebauthnVerify: (pendingToken: string, credentialJson: string) =>
    apiRequest<LoginSuccess>('/api/2fa/login/webauthn/verify', {
      method: 'POST',
      body: JSON.stringify({ pending_token: pendingToken, credential_json: credentialJson }),
    }),
}

export interface Driver {
  id: number
  driver_bot_id: string
  full_name: string
  telegram_group_id: number | null
  telegram_group_title: string | null
  dispatcher_username: string | null
  subscription_active: boolean
  samsara_vehicle_id: string | null
  load_count: number
  weekly_gross: number
  weekly_loads: number
}

export interface DriverLinkCode {
  code: string
  bot_command: string
}

// Response shape for POST /api/drivers - a freshly-created driver has none
// of Driver's load/earnings aggregates yet, so this is its own narrower
// type rather than extending Driver.
export interface NewDriver {
  id: number
  driver_bot_id: string
  full_name: string
  telegram_group_id: number | null
  telegram_group_title: string | null
  subscription_active: boolean
  link_code: string
  bot_command: string
}

export interface DriverLoad {
  id: number
  load_id: string
  broker_name: string | null
  pu_address: string | null
  del_address: string | null
  pu_date: string | null
  del_date: string | null
  rate_amount: number | null
  status: string
  created_at: string | null
}

export interface DriverDetail {
  id: number
  driver_bot_id: string
  full_name: string
  telegram_group_id: number | null
  telegram_group_title: string | null
  telegram_username: string | null
  dispatcher_username: string | null
  subscription_active: boolean
  samsara_vehicle_id: string | null
  weekly_gross: number
  weekly_loads: number
  total_gross: number
  total_loads: number
  loads: DriverLoad[]
}

export interface DashboardData {
  company_name: string
  stats: {
    total_drivers: number
    active_drivers: number
    total_loads: number
    weekly_gross: number
  }
  drivers: Driver[]
  billing?: BillingStatus
}

export interface Dispatcher {
  id: number
  username: string
  role: string
  created_at: string | null
}

export const dashboardApi = {
  getDashboard: () =>
    apiRequest<DashboardData>('/api/dashboard'),

  getDriverDetails: (driverId: number | string) =>
    apiRequest<DriverDetail>(`/api/drivers/${driverId}`),

  toggleSubscription: (driverId: number | string, active: boolean) =>
    apiRequest<{ status: string; active: boolean }>(`/api/drivers/${driverId}/subscription`, {
      method: 'PATCH',
      body: JSON.stringify({ active }),
    }),

  addDispatcher: (username: string, password: string) =>
    apiRequest<Dispatcher>('/api/dispatchers', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  listDispatchers: () =>
    apiRequest<Dispatcher[]>('/api/dispatchers'),

  updateDispatcher: (dispatcherId: number, updates: { username?: string; password?: string }) =>
    apiRequest<{ success: boolean }>(`/api/dispatchers/${dispatcherId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),

  deleteDispatcher: (dispatcherId: number) =>
    apiRequest<{ success: boolean }>(`/api/dispatchers/${dispatcherId}`, { method: 'DELETE' }),

  listDrivers: () =>
    apiRequest<Driver[]>('/api/drivers'),

  createDriver: (fullName: string) =>
    apiRequest<NewDriver>('/api/drivers', {
      method: 'POST',
      body: JSON.stringify({ full_name: fullName }),
    }),

  createDriverLinkToken: (driverId: number | string) =>
    apiRequest<DriverLinkCode>(`/api/drivers/${driverId}/link-token`, {
      method: 'POST',
    }),

  getMonitoring: () =>
    apiRequest<{
      samsara_connected: boolean
      vehicles: {
        id: number
        name: string
        driver_id: string
        vehicle_id: string | null
        active: boolean
        location: { lat?: number; lng?: number; updated_at?: string } | null
        load: { load_id: string; status: string; pickup: string; delivery: string; rate: number } | null
      }[]
    }>('/api/monitoring'),
}

export type AlertScenario = 'pu_near' | 'del_near'

export interface AlertRule {
  id: number
  scenario: AlertScenario
  distance_miles: number
  message_template: string | null
  enabled: boolean
}

export interface CompanySettings {
  gmail_connected: boolean
  samsara_connected: boolean
  company_name: string
  mc_number: string
}

export const settingsApi = {
  getSettings: () =>
    apiRequest<CompanySettings>('/api/settings'),

  listAlertRules: () => apiRequest<AlertRule[]>('/api/settings/alert-rules'),

  createAlertRule: (scenario: AlertScenario, distanceMiles: number, messageTemplate: string | null) =>
    apiRequest<AlertRule>('/api/settings/alert-rules', {
      method: 'POST',
      body: JSON.stringify({ scenario, distance_miles: distanceMiles, message_template: messageTemplate }),
    }),

  updateAlertRule: (id: number, fields: Partial<Pick<AlertRule, 'distance_miles' | 'message_template' | 'enabled'>>) =>
    apiRequest<AlertRule>(`/api/settings/alert-rules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(fields),
    }),

  deleteAlertRule: (id: number) =>
    apiRequest<{ deleted: boolean }>(`/api/settings/alert-rules/${id}`, { method: 'DELETE' }),

  // Kicks off the real Google OAuth flow: the backend returns a consent-screen
  // URL, the browser is sent there directly (no codes to copy/paste).
  // returnTo tells the backend where to redirect after Google's consent
  // screen - "settings" (default) or "onboarding" (mandatory first connect).
  getGmailAuthUrl: (returnTo: 'settings' | 'onboarding' = 'settings') =>
    apiRequest<{ auth_url: string }>(`/api/settings/gmail/connect?return_to=${returnTo}`),

  disconnectGmail: () =>
    apiRequest<{ success: boolean }>(
      '/api/settings/gmail',
      { method: 'DELETE' }
    ),

  connectSamsara: (apiKey: string) =>
    apiRequest<{ success: boolean; message: string }>(
      '/api/settings/samsara',
      { method: 'POST', body: JSON.stringify({ api_key: apiKey }) }
    ),

  disconnectSamsara: () =>
    apiRequest<{ success: boolean }>(
      '/api/settings/samsara',
      { method: 'DELETE' }
    ),
}

export const publicApi = {
  getStats: () =>
    apiRequest<{
      companies: number
      active_trucks: number
      loads_delivered: number
      loads_value: number
    }>('/api/public/stats'),

  // turnstile_site_key is null when Cloudflare Turnstile isn't configured -
  // the widget just doesn't render in that case and forms submit without it.
  getConfig: () => apiRequest<{ turnstile_site_key: string | null }>('/api/public/config'),
}

export interface BillingStatus {
  tier: 'free' | 'pro' | 'max_5x' | 'max_20x'
  status: 'none' | 'trialing' | 'active' | 'past_due' | 'canceled'
  trial_ends_at: string | null
  billing_interval: 'month' | 'year' | null
  max_drivers: number
  active_drivers: number
}

export const billingApi = {
  getStatus: () => apiRequest<BillingStatus>('/api/billing'),

  // Both return a Stripe-hosted URL - the caller redirects the browser
  // there with `window.location.href = url` rather than navigating in-app.
  checkout: (tier: 'pro' | 'max_5x' | 'max_20x', interval: 'month' | 'year') =>
    apiRequest<{ url: string }>('/api/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({ tier, interval }),
    }),

  openPortal: () => apiRequest<{ url: string }>('/api/billing/portal', { method: 'POST' }),
}
