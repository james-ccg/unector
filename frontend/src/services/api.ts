// API service for backend communication
const API_BASE = ''

// Two names, one cookie. In production the backend issues it with the
// __Host- prefix, which pins it to this exact origin so no subdomain can
// overwrite it - the attack the CSRF double-submit pattern otherwise falls
// to. The prefix requires Secure, so plain-http local dev cannot use it and
// gets the bare name. Read whichever is actually there.
const CSRF_COOKIE_NAMES = ['__Host-fp_csrf', 'fp_csrf']
const CSRF_HEADER_NAME = 'X-CSRF-Token'

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

function readCsrfToken(): string | null {
  for (const name of CSRF_COOKIE_NAMES) {
    const value = readCookie(name)
    if (value) return value
  }
  return null
}

type ApiOptions = RequestInit

/** A request that came back with an HTTP status we can't use.
 *
 * The message always ends with the status, because "Resource not found" and
 * "Server error" tell someone reporting a problem - and whoever they report
 * it to - nothing about which failure they actually hit. `status` is kept as
 * a field as well so a call site can branch on it without parsing prose. */
export class ApiError extends Error {
  readonly status: number
  /** The message without the "(HTTP nnn)" suffix. */
  readonly detail: string

  constructor(detail: string, status: number, options?: ErrorOptions) {
    super(`${detail} (HTTP ${status})`, options)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** A request that never got a status back at all. Named separately because
 * "the server said no" and "the server was never reached" are different
 * problems with different fixes, and a bare "Failed to fetch" from the
 * browser distinguishes neither. */
export class NetworkError extends Error {
  readonly kind: 'offline' | 'timeout' | 'unreachable' | 'malformed response'

  constructor(detail: string, kind: NetworkError['kind'], options?: ErrorOptions) {
    super(`${detail} (${kind})`, options)
    this.name = 'NetworkError'
    this.kind = kind
  }
}

/** Extracts a human-readable message from something caught in a try/catch.
 * apiRequest below always throws a real Error, but a catch clause's variable
 * is typed unknown (TS can't statically know what a call site threw), so
 * this is the one place that assumption lives.
 *
 * Anything thrown from here already names itself, so the fallback is only
 * reached for a non-Error someone threw by hand. */
export function errorMessage(err: unknown, fallback = 'Something went wrong.'): string {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'string' && err) return err
  return fallback
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
    const csrfToken = readCsrfToken()
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
        // On a failed response this is survivable - the status below is the
        // real information. On a successful one it is not: the caller is
        // about to read fields off an empty object and blame itself.
        if (response.ok) {
          throw new NetworkError(
            'The server sent a reply this app could not read',
            'malformed response',
            { cause: e }
          )
        }
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
          errorMsg = (body.detail as string) || 'Not found'
          break
        case 429:
          errorMsg = (body.detail as string) || 'Too many attempts. Wait a moment and try again.'
          break
        case 500:
          errorMsg = 'Server error. Please try again later.'
          break
        case 502:
        case 504:
          errorMsg = 'The server did not answer in time. Please try again.'
          break
        case 503:
          errorMsg = 'Service temporarily unavailable'
          break
      }

      throw new ApiError(errorMsg, response.status)
    }

    return data as T
  } catch (err: unknown) {
    clearTimeout(timeout)

    // Already named itself on the way past - don't wrap it twice.
    if (err instanceof ApiError || err instanceof NetworkError) throw err

    if ((err instanceof DOMException || err instanceof Error) && err.name === 'AbortError') {
      throw new NetworkError('The request took longer than 15 seconds', 'timeout', { cause: err })
    }

    if (!navigator.onLine) {
      throw new NetworkError('No internet connection', 'offline', { cause: err })
    }

    // fetch() rejects with a bare TypeError("Failed to fetch") for a refused
    // connection, a DNS failure or a CORS rejection alike, which tells the
    // person reading it nothing. Say what is actually known instead.
    if (err instanceof TypeError) {
      throw new NetworkError('Could not reach the server', 'unreachable', { cause: err })
    }

    throw err
  }
}

export interface TwoFaChallenge {
  requires_2fa: true
  pending_token: string
  methods: ('totp' | 'email' | 'sms' | 'telegram' | 'webauthn')[]
}

export interface AccountStatus {
  emoji: string | null
  text: string
  expires_at: string | null
}

export interface LoginSuccess {
  role: 'owner' | 'dispatcher'
  company_name?: string
  company_id: number
  dispatcher_id?: number
  // Only present for dispatchers - the owner's own name is company_name.
  username?: string
  // Only present for owners - Gmail connection is mandatory for them (the
  // bot's core feature depends on it), not applicable to dispatchers.
  gmail_connected?: boolean
  status?: AccountStatus | null
  avatar?: string | null
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
  // "Continue with Google" - returns the consent URL to send the browser to.
  // The rest of the flow happens as redirects, so there's no second call
  // here: the backend lands the browser back on /dashboard (session set) or
  // on /login with a ?google=... reason.
  // `switchAccount` drops the remembered address so Google shows its
  // chooser again - what the "Use a different account" link asks for.
  // `hinted_account` comes back so the button can name who it will sign in
  // as, rather than silently picking someone.
  googleLoginStart: (switchAccount = false) =>
    apiRequest<{ auth_url: string; hinted_account: string | null }>(
      `/api/auth/google/start${switchAccount ? '?switch_account=true' : ''}`
    ),

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

  setStatus: (text: string, emoji: string | null, expiresInMinutes: number | null) =>
    apiRequest<{ success: boolean }>('/api/me/status', {
      method: 'PUT',
      body: JSON.stringify({ text, emoji, expires_in_minutes: expiresInMinutes }),
    }),

  clearStatus: () => apiRequest<{ success: boolean }>('/api/me/status', { method: 'DELETE' }),

  setAvatar: (dataUrl: string) =>
    apiRequest<{ success: boolean }>('/api/me/avatar', {
      method: 'PUT',
      body: JSON.stringify({ data_url: dataUrl }),
    }),

  clearAvatar: () => apiRequest<{ success: boolean }>('/api/me/avatar', { method: 'DELETE' }),
}

export interface TeamMember {
  role: 'owner' | 'dispatcher'
  name: string
  avatar: string | null
}

export const teamApi = {
  list: () => apiRequest<TeamMember[]>('/api/team'),
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

/** A truck or trailer, identified by the unit number painted on it. */
export interface Unit {
  id: number
  unit_number: string
}

export interface Truck extends Unit {
  samsara_vehicle_id: string | null
  active: boolean
  trailer: Unit | null
  driver: {
    id: number
    full_name: string | null
    driver_bot_id: string
    telegram_group_title: string | null
    subscription_active: boolean
  } | null
}

export interface Trailer extends Unit {
  in_use: boolean
}

export interface Driver {
  id: number
  driver_bot_id: string
  full_name: string
  telegram_group_id: number | null
  telegram_group_title: string | null
  dispatcher_username: string | null
  subscription_active: boolean
  // Resolved through the driver's current truck - the GPS device is fitted
  // to the vehicle, not issued to the person.
  samsara_vehicle_id: string | null
  truck: Unit | null
  trailer: Unit | null
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

/** The stages a load moves through, in order: /dispatch creates it, then
 *  /loadpics, /bol and /pod each advance it. Only open loads (everything
 *  before pod_sent) appear in the fleet view. */
export type LoadStage = 'dispatched' | 'loaded' | 'bol_ok'

export interface FleetRow {
  driver_id: number
  driver_name: string
  driver_bot_id: string
  load_id: string
  status: LoadStage
  broker_name: string | null
  pickup: string | null
  delivery: string | null
  del_date: string | null
  rate_amount: number | null
  detention_since: string | null
  /** Empty when nothing is wrong; otherwise why this row needs looking at. */
  attention: ('detention' | 'overdue')[]
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
  fleet: FleetRow[]
  // Owners only - see CompanySettings.gmail_needs_reconnect.
  gmail_needs_reconnect?: boolean
  billing?: BillingStatus
}

export interface Dispatcher {
  id: number
  username: string
  role: string
  created_at: string | null
  avatar?: string | null
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

  deleteDriver: (driverId: number) =>
    apiRequest<{ success: boolean }>(`/api/drivers/${driverId}`, { method: 'DELETE' }),

  // Fleet assets - both owner and dispatcher can manage these.
  listTrucks: () => apiRequest<Truck[]>('/api/trucks'),

  createTruck: (unitNumber: string) =>
    apiRequest<Unit>('/api/trucks', {
      method: 'POST',
      body: JSON.stringify({ unit_number: unitNumber }),
    }),

  deleteTruck: (truckId: number) =>
    apiRequest<{ success: boolean }>(`/api/trucks/${truckId}`, { method: 'DELETE' }),

  /** Omit a field to leave it as it is; pass null to clear it. Sending
   *  `{ trailer_id: null }` unhooks the trailer without touching the driver. */
  assignTruck: (truckId: number, assignment: { driver_id?: number | null; trailer_id?: number | null }) =>
    apiRequest<{ success: boolean }>(`/api/trucks/${truckId}`, {
      method: 'PATCH',
      body: JSON.stringify(assignment),
    }),

  listTrailers: () => apiRequest<Trailer[]>('/api/trailers'),

  createTrailer: (unitNumber: string) =>
    apiRequest<Unit>('/api/trailers', {
      method: 'POST',
      body: JSON.stringify({ unit_number: unitNumber }),
    }),

  deleteTrailer: (trailerId: number) =>
    apiRequest<{ success: boolean }>(`/api/trailers/${trailerId}`, { method: 'DELETE' }),

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
  // 'ok'       - working, no action to offer
  // 'expiring' - still working, but Google will revoke it within ~2 days
  // 'expired'  - already rejected; nothing is being read from the inbox
  gmail_state?: 'ok' | 'expiring' | 'expired'
  gmail_expires_at?: string | null
  // Connected, but Google has stopped accepting the stored token - the
  // owner has to reconnect before the bot can read the inbox again.
  gmail_needs_reconnect?: boolean
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
