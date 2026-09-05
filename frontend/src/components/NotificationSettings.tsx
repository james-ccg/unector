import { useCallback, useEffect, useState } from 'react'
import {
  dashboardApi,
  errorMessage,
  type NotificationChannel,
  type NotificationEventPreference,
} from '../services/api'
import './NotificationSettings.css'

type TelegramLink = {
  code: string
  url: string | null
  bot_command: string
  expires_in_minutes: number
}

/**
 * What you get told about, and where.
 *
 * Laid out as one row per event with a chip per channel rather than as a
 * grid of checkboxes: a true matrix needs a header row to make sense of,
 * which stops working the moment the screen is narrow, and there are only
 * three channels to name.
 *
 * Two kinds of switch cannot move, and both are shown rather than hidden.
 * The dashboard list is the record of what was sent, so it is always on.
 * And anything with a real consequence - a failed payment, a sign-in nobody
 * recognises, an integration that stopped working - stays on, because the
 * person who muted it a year ago will not remember doing so on the day it
 * matters. Showing them locked is the point: people should be able to see
 * what they will be told about.
 */

const CHANNEL_ORDER: NotificationChannel[] = ['site', 'telegram', 'email']

export default function NotificationSettings() {
  const [rows, setRows] = useState<NotificationEventPreference[]>([])
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  // Whether the bot can reach this person at all, and the link that fixes
  // it when it cannot. Kept here rather than on the Security screen because
  // this is where somebody switches Telegram on and would otherwise never
  // learn that switching it on is not enough.
  const [telegramConnected, setTelegramConnected] = useState(true)
  const [link, setLink] = useState<TelegramLink | null>(null)
  const [linking, setLinking] = useState(false)
  const [linkError, setLinkError] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await dashboardApi.getNotificationPreferences()
      setRows(data.events)
      setLabels(Object.fromEntries(data.channels.map((c) => [c.key, c.label])))
      setTelegramConnected(data.telegram_connected)
      // Clears a stale link once the connection has actually happened, so
      // the panel does not keep offering a code that has been spent.
      if (data.telegram_connected) setLink(null)
      setError('')
    } catch (err) {
      setError(errorMessage(err, "Couldn't load your notification settings."))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    queueMicrotask(load)
  }, [load])

  const toggle = async (row: NotificationEventPreference, channel: NotificationChannel) => {
    const state = row.channels[channel]
    if (state.locked || !state.available) return

    const key = `${row.event}:${channel}`
    setBusy(key)
    setError('')

    // Moved first and put back on failure. A switch that waits for a round
    // trip before moving feels broken on a slow connection.
    const next = !state.enabled
    setRows((prev) =>
      prev.map((r) =>
        r.event === row.event
          ? { ...r, channels: { ...r.channels, [channel]: { ...state, enabled: next } } }
          : r
      )
    )

    try {
      await dashboardApi.setNotificationPreference(row.event, channel, next)
    } catch (err) {
      setRows((prev) =>
        prev.map((r) =>
          r.event === row.event
            ? { ...r, channels: { ...r.channels, [channel]: { ...state, enabled: !next } } }
            : r
        )
      )
      setError(errorMessage(err, "Couldn't save that change."))
    } finally {
      setBusy(null)
    }
  }

  const connect = async () => {
    setLinking(true)
    setLinkError('')
    try {
      setLink(await dashboardApi.startTelegramLink())
    } catch (err) {
      setLinkError(errorMessage(err, "Couldn't prepare a Telegram link."))
    } finally {
      setLinking(false)
    }
  }

  const disconnect = async () => {
    setLinking(true)
    setLinkError('')
    try {
      await dashboardApi.stopTelegramLink()
      await load()
    } catch (err) {
      // 409 while Telegram is also a two-factor method - the message says
      // which screen to turn that off on, so it is shown rather than
      // flattened into "couldn't do that".
      setLinkError(errorMessage(err, "Couldn't disconnect Telegram."))
    } finally {
      setLinking(false)
    }
  }

  if (loading) {
    return <p className="settings-hint">Loading your notification settings...</p>
  }

  // Grouped in the order the API sent them, which is the order the catalogue
  // declares - loads first, because that is what most people are here for.
  const categories: { key: string; label: string; rows: NotificationEventPreference[] }[] = []
  for (const row of rows) {
    let group = categories.find((c) => c.key === row.category)
    if (!group) {
      group = { key: row.category, label: row.category_label, rows: [] }
      categories.push(group)
    }
    group.rows.push(row)
  }

  return (
    <div className="ns">
      <p className="settings-hint ns-intro">
        The dashboard list always gets everything - it&apos;s the record of what was sent, and the
        one place nothing can go missing. Telegram and email are yours to choose, except where
        there&apos;s money or account access involved.
      </p>

      {/* Telegram cannot be delivered to until the person has opened a chat
          with the bot - Telegram refuses to let a bot message a stranger,
          and nothing on our side can grant that. So a switch turned on
          without it is indistinguishable from a working one, right up until
          the message somebody needed never arrives. This says so, and makes
          the one required step a single tap. */}
      {!telegramConnected && (
        <div className="ns-connect">
          <p className="ns-connect-text">
            <strong>Telegram isn&apos;t connected.</strong> Anything set to Telegram below
            won&apos;t arrive until it is. Telegram doesn&apos;t let a bot message someone who
            hasn&apos;t opened a chat with it, so it takes one tap - the link opens the bot, and
            pressing Start connects this account.
          </p>
          {linkError && <p className="ns-error">{linkError}</p>}
          {link ? (
            <div className="ns-connect-ready">
              {link.url && (
                <a
                  className="btn btn-primary btn-sm"
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open Telegram and connect
                </a>
              )}
              <p className="settings-hint">
                {link.url
                  ? 'No Telegram on this device? Send '
                  : "Couldn't build a link to the bot. Send "}
                <code className="mono">{link.bot_command}</code> to the bot instead. Good for{' '}
                {link.expires_in_minutes} minutes.
              </p>
              <button className="btn btn-ghost btn-sm" onClick={load}>
                I&apos;ve done it - check now
              </button>
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={connect} disabled={linking}>
              {linking ? 'Preparing...' : 'Connect Telegram'}
            </button>
          )}
        </div>
      )}

      {telegramConnected && (
        <div className="ns-connect is-done">
          <p className="ns-connect-text">
            <strong>Telegram is connected.</strong> Anything set to Telegram below arrives in
            your chat with the bot.
          </p>
          {linkError && <p className="ns-error">{linkError}</p>}
          <button className="btn btn-ghost btn-sm" onClick={disconnect} disabled={linking}>
            {linking ? 'Working...' : 'Disconnect Telegram'}
          </button>
        </div>
      )}

      {error && <p className="ns-error">{error}</p>}

      {categories.map((category) => (
        <div className="ns-group" key={category.key}>
          <h4 className="ns-group-title">{category.label}</h4>

          {category.rows.map((row) => (
            <div className="ns-row" key={row.event}>
              <div className="ns-what">
                <span className="ns-label">
                  {row.label}
                  {row.mandatory && <span className="ns-always">always on</span>}
                </span>
                <span className="ns-description">{row.description}</span>
              </div>

              <div className="ns-channels">
                {CHANNEL_ORDER.filter((channel) => row.channels[channel]?.available).map(
                  (channel) => {
                    const state = row.channels[channel]
                    const classes = ['ns-chip']
                    if (state.enabled) classes.push('is-on')
                    if (state.locked) classes.push('is-locked')
                    return (
                      <button
                        type="button"
                        key={channel}
                        className={classes.join(' ')}
                        onClick={() => toggle(row, channel)}
                        disabled={state.locked || busy === `${row.event}:${channel}`}
                        aria-pressed={state.enabled}
                        title={
                          state.locked
                            ? channel === 'site'
                              ? "The dashboard list can't be turned off - it's the record."
                              : "This one can't be turned off - it has a consequence attached."
                            : undefined
                        }
                      >
                        {labels[channel] ?? channel}
                      </button>
                    )
                  }
                )}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
