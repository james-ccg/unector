import { useCallback, useEffect, useRef, useState } from 'react'
import {
  dashboardApi,
  errorMessage,
  type NotificationChannel,
  type NotificationEventPreference,
} from '../services/api'
import './NotificationSettings.css'

type TelegramPresence = {
  connected: boolean
  username: string | null
  blocked: boolean
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
  // Whether the bot can reach this person at all. Needed here even though
  // connecting happens in Integrations: this is where somebody turns
  // Telegram on, and a switch that can never deliver has to say so at the
  // moment it is reached for.
  const [telegram, setTelegram] = useState<TelegramPresence>({
    connected: true, username: null, blocked: false,
  })

  // Which chip is explaining itself, as "event:channel". A bubble beside the
  // thing that was pressed, rather than a line at the top of a list somebody
  // has scrolled down past - the message is about the chip, so it belongs
  // where the chip is.
  const [hint, setHint] = useState<string | null>(null)
  const hintTimer = useRef<number | null>(null)

  const showHint = (event: string, channel: NotificationChannel) => {
    if (hintTimer.current) window.clearTimeout(hintTimer.current)
    setHint(`${event}:${channel}`)
    // Long enough to read one sentence, short enough not to be dismissed
    // furniture. Cleared on unmount too, or it sets state on a gone component.
    hintTimer.current = window.setTimeout(() => setHint(null), 2600)
  }

  useEffect(() => () => {
    if (hintTimer.current) window.clearTimeout(hintTimer.current)
  }, [])

  const load = useCallback(async () => {
    try {
      const data = await dashboardApi.getNotificationPreferences()
      setRows(data.events)
      setLabels(Object.fromEntries(data.channels.map((c) => [c.key, c.label])))
      setTelegram(data.telegram)
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

    // With nothing connected the switch means nothing in either direction:
    // on would save a preference that can never deliver, and off would be
    // turning off something that was never going to arrive. So it is locked
    // both ways, and says why beside the chip that was pressed rather than
    // in a banner at the top the reader may have scrolled past.
    if (channel === 'telegram' && !telegram.connected) {
      showHint(row.event, channel)
      return
    }

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

      {/* Connecting lives in Integrations, beside Gmail and Samsara - it is
          a connection to an outside account, which is what that tab is for.
          This is the pointer, in the shape of the one the dashboard uses to
          send people to the Gmail card.

          A bare #telegram href is enough: the tabs hide sections rather
          than unmounting them, and SettingsPage listens for hashchange to
          switch to the tab that holds the target. */}
      {!telegram.connected && (
        <p className="ns-notice">
          <strong>Telegram isn&apos;t connected</strong>, so the Telegram switches below are
          unavailable. <a href="#telegram">Connect it in Integrations</a>{' '}
          and they turn on.
        </p>
      )}
      {telegram.connected && telegram.blocked && (
        <p className="ns-notice">
          <strong>You&apos;ve blocked the bot in Telegram</strong>, so nothing set to Telegram is
          arriving. Unblocking it is all it takes -{' '}
          <a href="#telegram">see Integrations</a>.
        </p>
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
                    // Unreachable in both directions: with nothing connected
                    // there is no meaningful on and no meaningful off.
                    const unreachable = channel === 'telegram' && !telegram.connected
                    const key = `${row.event}:${channel}`
                    const classes = ['ns-chip']
                    if (state.enabled) classes.push('is-on')
                    if (state.locked) classes.push('is-locked')
                    if (unreachable) classes.push('is-unavailable')
                    return (
                      <span className="ns-chip-wrap" key={channel}>
                      {hint === key && (
                        // Absolutely positioned, so appearing and going away
                        // moves nothing else on the page - a row that grew
                        // and shrank would shove the rest of the list about
                        // every time somebody pressed a locked chip.
                        <span className="ns-hint" role="status">
                          Connect Telegram in Integrations first - until then there&apos;s nowhere
                          to send it.
                        </span>
                      )}
                      <button
                        type="button"
                        className={classes.join(' ')}
                        onClick={() => toggle(row, channel)}
                        // Not `disabled` for the unreachable case: a disabled
                        // button fires no click, so pressing it would explain
                        // nothing and feel broken instead.
                        disabled={state.locked || busy === key}
                        aria-pressed={state.enabled}
                        title={
                          state.locked
                            ? channel === 'site'
                              ? "The dashboard list can't be turned off - it's the record."
                              : "This one can't be turned off - it has a consequence attached."
                            : unreachable
                              ? 'Connect Telegram in Integrations first.'
                              : undefined
                        }
                      >
                        {labels[channel] ?? channel}
                      </button>
                      </span>
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
