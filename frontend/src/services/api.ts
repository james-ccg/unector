// API service for backend communication
const API_BASE = ''

const CSRF_COOKIE_NAME = 'fp_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

type ApiOptions = RequestInit

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

    let data: any = {}
    const contentType = response.headers.get('content-type')
    if (contentType?.includes('application/json')) {
      try {
        data = await response.json()
      } catch (e) {
        console.error('Failed to parse JSON response:', e)
      }
    }

    if (!response.ok) {
      let errorMsg = data.detail || data.message || 'Request failed'

      switch (response.status) {
        case 401:
          errorMsg = 'Session expired. Please log in again.'
          break
        case 403:
          errorMsg = data.detail || 'Access denied'
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
  } catch (err: any) {
    clearTimeout(timeout)

    if (err.name === 'AbortError') {
      throw new Error('Request timeout. Please check your connection.')
    }

    if (!navigator.onLine) {
      throw new Error('No internet connection')
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
  }) =>
    apiRequest<LoginSuccess>(
      '/api/auth/register',
      { method: 'POST', body: JSON.stringify(data) }
    ),

  logout: () => apiRequest<{ success: boolean }>('/api/auth/logout', { method: 'POST' }),

  // Called on app load to check whether the httpOnly session cookie (if any)
  // is still valid - the frontend never sees the token itself, only this result.
  me: () => apiRequest<LoginSuccess>('/api/me'),
}

export const twoFaApi = {
  // ---- while already logged in: Settings > Security ----
  getStatus: () =>
    apiRequest<{
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
    }>('/api/2fa/status'),

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
    apiRequest<{ options: string; challenge: string }>('/api/2fa/webauthn/register/options', {
      method: 'POST',
    }),
  webauthnRegisterVerify: (credentialJson: string, challenge: string, label: string) =>
    apiRequest<{ registered: boolean }>('/api/2fa/webauthn/register/verify', {
      method: 'POST',
      body: JSON.stringify({ credential_json: credentialJson, challenge, label }),
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
    apiRequest<{ options: string; challenge: string }>('/api/2fa/login/webauthn/options', {
      method: 'POST',
      headers: { Authorization: `Bearer ${pendingToken}` },
    }),
  loginWebauthnVerify: (pendingToken: string, credentialJson: string, challenge: string) =>
    apiRequest<LoginSuccess>(`/api/2fa/login/webauthn/verify?pending_token=${encodeURIComponent(pendingToken)}`, {
      method: 'POST',
      body: JSON.stringify({ credential_json: credentialJson, challenge }),
    }),
}

export const dashboardApi = {
  getDashboard: () =>
    apiRequest<any>('/api/dashboard'),

  getDriverDetails: (driverId: string) =>
    apiRequest<any>(`/api/drivers/${driverId}`),

  addDispatcher: (username: string, password: string) =>
    apiRequest<any>('/api/dispatchers', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  listDispatchers: () =>
    apiRequest<{ id: number; username: string; role: string; created_at: string | null }[]>(
      '/api/dispatchers'
    ),

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

export const settingsApi = {
  getSettings: () =>
    apiRequest<{
      gmail_connected: boolean
      samsara_connected: boolean
      company_name: string
      mc_number: string
    }>('/api/settings'),

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
      uptime: number
    }>('/api/public/stats'),

  // turnstile_site_key is null when Cloudflare Turnstile isn't configured -
  // the widget just doesn't render in that case and forms submit without it.
  getConfig: () => apiRequest<{ turnstile_site_key: string | null }>('/api/public/config'),
}
