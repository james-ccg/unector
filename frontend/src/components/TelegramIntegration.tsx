import { useCallback, useEffect, useState } from 'react'
import Icon from './Icon'
import { dashboardApi, errorMessage } from '../services/api'

/**
 * Connecting a Telegram account, as an integration card.
 *
 * It belongs here beside Gmail and Samsara rather than inside the
 * notification switches: it is a connection to an outside account, which is
 * what this tab is, and the switches are a separate question about what to
 * send once one exists. Notifications links across to it.
 *
 * The thing this is all shaped around is Telegram's rule, not ours: a bot
 * cannot message somebody who has never opened a chat with it. So there is
 * no way to skip the step, only to make it one tap - the link opens the bot
 * with a token attached, and pressing Start both begins the conversation
 * Telegram insists on and connects the account.
 */

type Presence = { connected: boolean; username: string | null; blocked: boolean }
type Link = { code: string; url: string | null; bot_command: string; expires_in_minutes: number }

export default function TelegramIntegration() {
  const [presence, setPresence] = useState<Presence>({
    connected: false, username: null, blocked: false,
  })
  const [link, setLink] = useState<Link | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await dashboardApi.getNotificationPreferences()
      setPresence(data.telegram)
      // Drops a spent link once the connection has actually happened, so the
      // card stops offering a code that will no longer work.
      if (data.telegram.connected) setLink(null)
    } catch {
      // The notification screen shows this failure properly. Here it would
      // only be a second copy of the same red text on the same page.
    }
  }, [])

  useEffect(() => {
    queueMicrotask(load)
  }, [load])

  const connect = async () => {
    setBusy(true)
    setError('')
    try {
      setLink(await dashboardApi.startTelegramLink())
    } catch (err) {
      setError(errorMessage(err, "Couldn't prepare a Telegram link."))
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    setBusy(true)
    setError('')
    try {
      await dashboardApi.stopTelegramLink()
      await load()
    } catch (err) {
      // 409 while Telegram is also a two-factor method. The message names
      // the screen to turn that off on, so it is shown rather than
      // flattened into "couldn't do that".
      setError(errorMessage(err, "Couldn't disconnect Telegram."))
    } finally {
      setBusy(false)
    }
  }

  // Three states, not two. Blocked is connected and delivering nothing, and
  // showing it as either of the others hides the one fact that explains why
  // nothing is arriving.
  const badge = !presence.connected
    ? { className: 'is-disconnected', text: 'Not connected' }
    : presence.blocked
      ? { className: 'is-warning', text: 'Blocked' }
      : { className: 'is-connected', text: 'Connected' }

  return (
    <div className="card integration-card" id="telegram">
      <div className="integration-header">
        <div className="integration-icon"><Icon name="telegram" size={22} /></div>
        <div className="integration-info">
          <h3>Telegram</h3>
          <p>
            Where notifications reach you outside the dashboard - loads, billing, and anything
            about your account&apos;s security.
          </p>
          {presence.connected && presence.username && (
            <p className="integration-account mono">{presence.username}</p>
          )}
        </div>
        <span className={`status-badge ${badge.className}`}>{badge.text}</span>
      </div>

      {presence.blocked && (
        <p className="settings-hint">
          You&apos;ve blocked the bot in Telegram, so nothing can be delivered. The connection is
          still here - unblocking it is all it takes, and messages start arriving again by
          themselves. Nothing needs reconnecting.
        </p>
      )}

      {!presence.connected && (
        <p className="settings-hint">
          Telegram doesn&apos;t let a bot message someone who hasn&apos;t opened a chat with it, so
          this takes one tap: the link opens the bot, and pressing Start connects your account.
        </p>
      )}

      {error && <p className="form-error">{error}</p>}

      <div className="integration-actions">
        {presence.connected ? (
          <button className="btn btn-danger-ghost" onClick={disconnect} disabled={busy}>
            {busy ? 'Working...' : 'Disconnect'}
          </button>
        ) : link ? (
          <>
            {link.url && (
              <a
                className="btn btn-primary"
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Telegram and connect
              </a>
            )}
            <button className="btn btn-ghost" onClick={load}>
              I&apos;ve done it - check now
            </button>
          </>
        ) : (
          <button className="btn btn-primary" onClick={connect} disabled={busy}>
            {busy ? 'Preparing...' : 'Connect Telegram'}
          </button>
        )}
      </div>

      {!presence.connected && link && (
        <p className="settings-hint">
          {link.url ? 'No Telegram on this device? Send ' : "Couldn't build a link to the bot. Send "}
          <code className="mono">{link.bot_command}</code> to the bot instead. Good for{' '}
          {link.expires_in_minutes} minutes.
        </p>
      )}
    </div>
  )
}
