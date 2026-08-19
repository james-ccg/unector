// API service for backend communication
const API_BASE = ''

interface ApiOptions extends RequestInit {
  token?: string
}

export async function apiRequest<T>(
  path: string,
  options: ApiOptions = {}
): Promise<T> {
  const { token, ...fetchOptions } = options
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (fetchOptions.headers) {
    Object.entries(fetchOptions.headers).forEach(([key, value]) => {
      headers[key] = String(value)
    })
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)

  try {
    const response = await fetch(API_BASE + path, {
      ...fetchOptions,
      headers,
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
          localStorage.removeItem('fp_token')
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
  token: string
  role: 'owner' | 'dispatcher'
  company_name?: string
  company_id: number
  dispatcher_id?: number
}

export const authApi = {
  loginOwner: (mcNumber: string, password: string) =>
    apiRequest<LoginSuccess | TwoFaChallenge>('/api/auth/owner', {
      method: 'POST',
      body: JSON.stringify({ mc_number: mcNumber, password }),
    }),

  loginDispatcher: (username: string, password: string) =>
    apiRequest<LoginSuccess | TwoFaChallenge>('/api/auth/dispatcher', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  register: (data: {
    mc_number: string
    company_name: string
    email: string
    password: string
    confirm_password: string
  }) =>
    apiRequest<{ token: string; role: string; company_name: string; company_id: number }>(
      '/api/auth/register',
      { method: 'POST', body: JSON.stringify(data) }
    ),
}

export const twoFaApi = {
  // ---- while already logged in: Settings > Security ----
  getStatus: (token: string) =>
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
    }>('/api/2fa/status', { token }),

  totpSetup: (token: string) =>
    apiRequest<{ secret: string; qr_code: string }>('/api/2fa/totp/setup', { method: 'POST', token }),
  totpVerify: (code: string, token: string) =>
    apiRequest<{ enabled: boolean }>('/api/2fa/totp/verify', {
      method: 'POST',
      body: JSON.stringify({ channel: 'totp', code }),
      token,
    }),
  totpDisable: (token: string) =>
    apiRequest<{ enabled: boolean }>('/api/2fa/totp', { method: 'DELETE', token }),

  otpSend: (channel: 'email' | 'sms' | 'telegram', contact: string | null, token: string) =>
    apiRequest<{ sent: boolean }>('/api/2fa/otp/send', {
      method: 'POST',
      body: JSON.stringify({ channel, contact }),
      token,
    }),
  otpConfirm: (channel: 'email' | 'sms' | 'telegram', code: string, contact: string | null, token: string) =>
    apiRequest<{ enabled: boolean }>(`/api/2fa/otp/confirm?contact=${encodeURIComponent(contact || '')}`, {
      method: 'POST',
      body: JSON.stringify({ channel, code }),
      token,
    }),
  otpDisable: (channel: 'email' | 'sms' | 'telegram', token: string) =>
    apiRequest<{ enabled: boolean }>(`/api/2fa/otp/${channel}`, { method: 'DELETE', token }),

  telegramLinkStart: (token: string) =>
    apiRequest<{ code: string; bot_command: string }>('/api/2fa/telegram/link/start', { method: 'POST', token }),

  webauthnList: (token: string) =>
    apiRequest<{ id: number; label: string | null; created_at: string | null }[]>('/api/2fa/webauthn', { token }),

  webauthnRegisterOptions: (token: string) =>
    apiRequest<{ options: string; challenge: string }>('/api/2fa/webauthn/register/options', {
      method: 'POST',
      token,
    }),
  webauthnRegisterVerify: (credentialJson: string, challenge: string, label: string, token: string) =>
    apiRequest<{ registered: boolean }>('/api/2fa/webauthn/register/verify', {
      method: 'POST',
      body: JSON.stringify({ credential_json: credentialJson, challenge, label }),
      token,
    }),
  webauthnDelete: (credentialPk: number, token: string) =>
    apiRequest<{ deleted: boolean }>(`/api/2fa/webauthn/${credentialPk}`, { method: 'DELETE', token }),

  recoveryCodesGenerate: (token: string) =>
    apiRequest<{ codes: string[] }>('/api/2fa/recovery-codes/generate', { method: 'POST', token }),

  // ---- during login, before the session token exists ----
  loginChallenge: (channel: 'email' | 'sms' | 'telegram', pendingToken: string) =>
    apiRequest<{ sent: boolean }>('/api/2fa/login/challenge', {
      method: 'POST',
      body: JSON.stringify({ channel }),
      token: pendingToken,
    }),
  loginVerify: (pendingToken: string, method: string, code: string) =>
    apiRequest<LoginSuccess>('/api/2fa/login/verify', {
      method: 'POST',
      body: JSON.stringify({ pending_token: pendingToken, method, code }),
    }),
  loginWebauthnOptions: (pendingToken: string) =>
    apiRequest<{ options: string; challenge: string }>('/api/2fa/login/webauthn/options', {
      method: 'POST',
      token: pendingToken,
    }),
  loginWebauthnVerify: (pendingToken: string, credentialJson: string, challenge: string) =>
    apiRequest<LoginSuccess>(`/api/2fa/login/webauthn/verify?pending_token=${encodeURIComponent(pendingToken)}`, {
      method: 'POST',
      body: JSON.stringify({ credential_json: credentialJson, challenge }),
    }),
}

export const dashboardApi = {
  getDashboard: (token: string) =>
    apiRequest<any>('/api/dashboard', { token }),

  getDriverDetails: (driverId: string, token: string) =>
    apiRequest<any>(`/api/drivers/${driverId}`, { token }),

  addDispatcher: (username: string, password: string, token: string) =>
    apiRequest<any>('/api/dispatchers', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
      token,
    }),

  listDispatchers: (token: string) =>
    apiRequest<{ id: number; username: string; role: string; created_at: string | null }[]>(
      '/api/dispatchers',
      { token }
    ),

  getMonitoring: (token: string) =>
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
    }>('/api/monitoring', { token }),
}

export const settingsApi = {
  getSettings: (token: string) =>
    apiRequest<{
      gmail_connected: boolean
      samsara_connected: boolean
      company_name: string
      mc_number: string
    }>('/api/settings', { token }),

  // Kicks off the real Google OAuth flow: the backend returns a consent-screen
  // URL, the browser is sent there directly (no codes to copy/paste).
  getGmailAuthUrl: (token: string) =>
    apiRequest<{ auth_url: string }>('/api/settings/gmail/connect', { token }),

  disconnectGmail: (token: string) =>
    apiRequest<{ success: boolean }>(
      '/api/settings/gmail',
      { method: 'DELETE', token }
    ),

  connectSamsara: (apiKey: string, token: string) =>
    apiRequest<{ success: boolean; message: string }>(
      '/api/settings/samsara',
      { method: 'POST', body: JSON.stringify({ api_key: apiKey }), token }
    ),

  disconnectSamsara: (token: string) =>
    apiRequest<{ success: boolean }>(
      '/api/settings/samsara',
      { method: 'DELETE', token }
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
}
