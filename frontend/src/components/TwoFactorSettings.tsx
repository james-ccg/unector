import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { twoFaApi, errorMessage, type TwoFaStatus } from '../services/api'
import { isWebAuthnSupported, createCredential } from '../services/webauthn'
import Icon from './Icon'
import Alert from './Alert'

type Banner = { kind: 'success' | 'error'; text: string } | null

export default function TwoFactorSettings() {
  const { user } = useAuth()
  const [status, setStatus] = useState<TwoFaStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<Banner>(null)

  const [totpQr, setTotpQr] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpBusy, setTotpBusy] = useState(false)

  const [emailInput, setEmailInput] = useState('')
  const [emailCode, setEmailCode] = useState('')
  const [emailSent, setEmailSent] = useState(false)
  const [emailBusy, setEmailBusy] = useState(false)

  const [smsInput, setSmsInput] = useState('')
  const [smsCode, setSmsCode] = useState('')
  const [smsSent, setSmsSent] = useState(false)
  const [smsBusy, setSmsBusy] = useState(false)

  const [telegramCode, setTelegramCode] = useState<string | null>(null)
  const [telegramBusy, setTelegramBusy] = useState(false)

  const [webauthnCreds, setWebauthnCreds] = useState<{ id: number; label: string | null }[]>([])
  const [webauthnBusy, setWebauthnBusy] = useState(false)
  const [webauthnLabel, setWebauthnLabel] = useState('')

  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [recoveryBusy, setRecoveryBusy] = useState(false)

  const load = useCallback(async () => {
    if (!user) return
    try {
      const [statusData, creds] = await Promise.all([
        twoFaApi.getStatus(),
        twoFaApi.webauthnList(),
      ])
      setStatus(statusData)
      setWebauthnCreds(creds)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
  }, [load])

  const flash = (kind: 'success' | 'error', text: string) => {
    setBanner({ kind, text })
    window.setTimeout(() => setBanner(null), 6000)
  }

  // ---------------- TOTP ----------------
  const startTotpSetup = async () => {
    if (!user) return
    try {
      const { qr_code } = await twoFaApi.totpSetup()
      setTotpQr(qr_code)
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  const confirmTotp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setTotpBusy(true)
    try {
      await twoFaApi.totpVerify(totpCode)
      setTotpQr(null)
      setTotpCode('')
      flash('success', 'Authenticator app enabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setTotpBusy(false)
    }
  }

  const disableTotp = async () => {
    if (!user) return
    try {
      await twoFaApi.totpDisable()
      flash('success', 'Authenticator app disabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  // ---------------- Email ----------------
  const sendEmailCode = async () => {
    if (!user || !emailInput.trim()) return
    setEmailBusy(true)
    try {
      await twoFaApi.otpSend('email', emailInput.trim())
      setEmailSent(true)
      flash('success', 'Verification code sent to your email.')
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setEmailBusy(false)
    }
  }

  const confirmEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setEmailBusy(true)
    try {
      await twoFaApi.otpConfirm('email', emailCode, emailInput.trim())
      setEmailSent(false)
      setEmailCode('')
      setEmailInput('')
      flash('success', 'Email verification enabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setEmailBusy(false)
    }
  }

  const disableEmail = async () => {
    if (!user) return
    try {
      await twoFaApi.otpDisable('email')
      flash('success', 'Email verification disabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  // ---------------- SMS ----------------
  const sendSmsCode = async () => {
    if (!user || !smsInput.trim()) return
    setSmsBusy(true)
    try {
      await twoFaApi.otpSend('sms', smsInput.trim())
      setSmsSent(true)
      flash('success', 'Verification code sent by text message.')
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setSmsBusy(false)
    }
  }

  const confirmSms = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setSmsBusy(true)
    try {
      await twoFaApi.otpConfirm('sms', smsCode, smsInput.trim())
      setSmsSent(false)
      setSmsCode('')
      setSmsInput('')
      flash('success', 'Text message verification enabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setSmsBusy(false)
    }
  }

  const disableSms = async () => {
    if (!user) return
    try {
      await twoFaApi.otpDisable('sms')
      flash('success', 'Text message verification disabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  // ---------------- Telegram ----------------
  const startTelegramLink = async () => {
    if (!user) return
    setTelegramBusy(true)
    try {
      const { code } = await twoFaApi.telegramLinkStart()
      setTelegramCode(code)
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setTelegramBusy(false)
    }
  }

  const checkTelegramLinked = async () => {
    setTelegramBusy(true)
    await load()
    setTelegramBusy(false)
    if (status?.telegram_linked) {
      setTelegramCode(null)
      flash('success', 'Telegram linked.')
    }
  }

  const disableTelegram = async () => {
    if (!user) return
    try {
      await twoFaApi.otpDisable('telegram')
      flash('success', 'Telegram verification disabled.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  // ---------------- Security keys ----------------
  const registerSecurityKey = async () => {
    if (!user) return
    if (!isWebAuthnSupported()) {
      flash('error', 'This browser does not support security keys.')
      return
    }
    setWebauthnBusy(true)
    try {
      const { options } = await twoFaApi.webauthnRegisterOptions()
      const credentialJson = await createCredential(options)
      await twoFaApi.webauthnRegisterVerify(credentialJson, webauthnLabel || 'Security key')
      setWebauthnLabel('')
      flash('success', 'Security key registered.')
      load()
    } catch (err) {
      flash('error', errorMessage(err, "Couldn't register security key."))
    } finally {
      setWebauthnBusy(false)
    }
  }

  const removeSecurityKey = async (id: number) => {
    if (!user) return
    try {
      await twoFaApi.webauthnDelete(id)
      flash('success', 'Security key removed.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    }
  }

  // ---------------- Recovery codes ----------------
  const generateRecoveryCodes = async () => {
    if (!user) return
    setRecoveryBusy(true)
    try {
      const { codes } = await twoFaApi.recoveryCodesGenerate()
      setRecoveryCodes(codes)
      flash('success', 'New recovery codes generated - save them now, they will not be shown again.')
      load()
    } catch (err) {
      flash('error', errorMessage(err))
    } finally {
      setRecoveryBusy(false)
    }
  }

  if (loading) return <p className="empty">Loading security settings...</p>

  return (
    <div className="twofa-section">
      {banner && (
        <Alert kind={banner.kind} onDismiss={() => setBanner(null)}>
          {banner.text}
        </Alert>
      )}

      {/* ---------------- Authenticator app ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="shield" size={20} /></div>
          <div className="twofa-info">
            <h3>Authenticator app</h3>
            <p>Google Authenticator, Authy, 1Password, or any TOTP app.</p>
          </div>
          <span className={`status-badge ${status?.totp_enabled ? 'is-connected' : 'is-disconnected'}`}>
            {status?.totp_enabled ? 'Enabled' : 'Not enabled'}
          </span>
        </div>

        {status?.totp_enabled ? (
          <button className="btn-danger-ghost" onClick={disableTotp}>Disable</button>
        ) : totpQr ? (
          <form onSubmit={confirmTotp} className="twofa-enroll">
            <img src={totpQr} alt="Scan this QR code with your authenticator app" className="totp-qr" />
            <p className="method-hint">Scan the QR code, then enter the 6-digit code it shows.</p>
            <div className="inline-form">
              <input
                type="text"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="123456"
                maxLength={6}
              />
              <button className="btn btn-primary" disabled={totpBusy || totpCode.length < 6}>
                {totpBusy ? 'Verifying...' : 'Confirm'}
              </button>
            </div>
          </form>
        ) : (
          <button className="btn btn-primary" onClick={startTotpSetup}>Set up</button>
        )}
      </div>

      {/* ---------------- Email ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="email" size={20} /></div>
          <div className="twofa-info">
            <h3>Email code</h3>
            <p>{status?.contact_email ? `Sent to ${status.contact_email}` : 'Get a one-time code by email.'}</p>
          </div>
          <span className={`status-badge ${status?.email_otp_enabled ? 'is-connected' : 'is-disconnected'}`}>
            {status?.email_otp_enabled ? 'Enabled' : 'Not enabled'}
          </span>
        </div>

        {status?.email_otp_enabled ? (
          <button className="btn-danger-ghost" onClick={disableEmail}>Disable</button>
        ) : (
          <div className="twofa-enroll">
            {!emailSent ? (
              <div className="inline-form">
                <input type="email" value={emailInput} onChange={(e) => setEmailInput(e.target.value)} placeholder="you@example.com" />
                <button className="btn btn-primary" onClick={sendEmailCode} disabled={emailBusy || !emailInput.trim()}>
                  {emailBusy ? 'Sending...' : 'Send code'}
                </button>
              </div>
            ) : (
              <form onSubmit={confirmEmail} className="inline-form">
                <input type="text" value={emailCode} onChange={(e) => setEmailCode(e.target.value)} placeholder="123456" maxLength={6} autoFocus />
                <button className="btn btn-primary" disabled={emailBusy || emailCode.length < 6}>
                  {emailBusy ? 'Verifying...' : 'Confirm'}
                </button>
              </form>
            )}
          </div>
        )}
      </div>

      {/* ---------------- SMS ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="phone" size={20} /></div>
          <div className="twofa-info">
            <h3>Text message</h3>
            <p>{status?.phone_number ? `Sent to ${status.phone_number}` : 'Requires a connected SMS provider (e.g. Twilio).'}</p>
          </div>
          <span className={`status-badge ${status?.sms_otp_enabled ? 'is-connected' : 'is-disconnected'}`}>
            {status?.sms_otp_enabled ? 'Enabled' : 'Not enabled'}
          </span>
        </div>

        {status?.sms_otp_enabled ? (
          <button className="btn-danger-ghost" onClick={disableSms}>Disable</button>
        ) : (
          <div className="twofa-enroll">
            {!smsSent ? (
              <div className="inline-form">
                <input type="tel" value={smsInput} onChange={(e) => setSmsInput(e.target.value)} placeholder="+1 555 123 4567" />
                <button className="btn btn-primary" onClick={sendSmsCode} disabled={smsBusy || !smsInput.trim()}>
                  {smsBusy ? 'Sending...' : 'Send code'}
                </button>
              </div>
            ) : (
              <form onSubmit={confirmSms} className="inline-form">
                <input type="text" value={smsCode} onChange={(e) => setSmsCode(e.target.value)} placeholder="123456" maxLength={6} autoFocus />
                <button className="btn btn-primary" disabled={smsBusy || smsCode.length < 6}>
                  {smsBusy ? 'Verifying...' : 'Confirm'}
                </button>
              </form>
            )}
          </div>
        )}
      </div>

      {/* ---------------- Telegram ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="location" size={20} /></div>
          <div className="twofa-info">
            <h3>Telegram</h3>
            <p>Get a one-time code as a message from the Freight Pilot bot.</p>
          </div>
          <span className={`status-badge ${status?.telegram_otp_enabled ? 'is-connected' : 'is-disconnected'}`}>
            {status?.telegram_otp_enabled ? 'Enabled' : status?.telegram_linked ? 'Linked' : 'Not linked'}
          </span>
        </div>

        {status?.telegram_otp_enabled ? (
          <button className="btn-danger-ghost" onClick={disableTelegram}>Disable</button>
        ) : telegramCode ? (
          <div className="twofa-enroll">
            <p className="method-hint">
              In Telegram, message the bot: <code className="mono">/verify2fa {telegramCode}</code>
            </p>
            <button className="btn btn-primary" onClick={checkTelegramLinked} disabled={telegramBusy}>
              {telegramBusy ? 'Checking...' : "I've sent it - check now"}
            </button>
          </div>
        ) : (
          <button className="btn btn-primary" onClick={startTelegramLink} disabled={telegramBusy}>
            {telegramBusy ? 'Generating...' : 'Link Telegram'}
          </button>
        )}
      </div>

      {/* ---------------- Security keys ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="check" size={20} /></div>
          <div className="twofa-info">
            <h3>Security keys</h3>
            <p>YubiKey, Touch ID, Windows Hello, or any FIDO2/WebAuthn device.</p>
          </div>
          <span className={`status-badge ${webauthnCreds.length ? 'is-connected' : 'is-disconnected'}`}>
            {webauthnCreds.length} registered
          </span>
        </div>

        {webauthnCreds.length > 0 && (
          <div className="dispatcher-list" style={{ marginBottom: 14 }}>
            {webauthnCreds.map((c) => (
              <div key={c.id} className="dispatcher-row">
                <span className="status-dot on" />
                <span className="dispatcher-username">{c.label || 'Security key'}</span>
                <button className="icon-button" onClick={() => removeSecurityKey(c.id)} aria-label="Remove">
                  <Icon name="close" size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="inline-form">
          <input
            type="text"
            value={webauthnLabel}
            onChange={(e) => setWebauthnLabel(e.target.value)}
            placeholder="Name this key (e.g. 'YubiKey')"
          />
          <button className="btn btn-primary" onClick={registerSecurityKey} disabled={webauthnBusy || !isWebAuthnSupported()}>
            {webauthnBusy ? 'Registering...' : 'Add security key'}
          </button>
        </div>
        {!isWebAuthnSupported() && <p className="method-hint">This browser does not support security keys.</p>}
      </div>

      {/* ---------------- Recovery codes ---------------- */}
      <div className="card twofa-card">
        <div className="twofa-card-head">
          <div className="twofa-icon"><Icon name="warning" size={20} /></div>
          <div className="twofa-info">
            <h3>Recovery codes</h3>
            <p>{status?.recovery_codes_remaining || 0} unused codes remaining. Use one if you lose access to your other methods.</p>
          </div>
        </div>

        {recoveryCodes ? (
          <>
            <div className="recovery-code-grid">
              {recoveryCodes.map((c) => (
                <code key={c} className="recovery-code">{c}</code>
              ))}
            </div>
            <p className="method-hint">Save these somewhere safe - they won't be shown again.</p>
            <button className="btn btn-ghost" onClick={() => setRecoveryCodes(null)}>I've saved these</button>
          </>
        ) : (
          <button className="btn btn-primary" onClick={generateRecoveryCodes} disabled={recoveryBusy}>
            {recoveryBusy ? 'Generating...' : 'Generate recovery codes'}
          </button>
        )}
      </div>
    </div>
  )
}
