import { useCallback, useEffect, useState } from 'react'
import {
  dashboardApi,
  errorMessage,
  type NotificationChannel,
  type NotificationEventPreference,
} from '../services/api'
import './NotificationSettings.css'

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

  const load = useCallback(async () => {
    try {
      const data = await dashboardApi.getNotificationPreferences()
      setRows(data.events)
      setLabels(Object.fromEntries(data.channels.map((c) => [c.key, c.label])))
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
