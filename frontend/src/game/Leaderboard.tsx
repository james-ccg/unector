import { useEffect, useState } from 'react'
import { getLeaderboard, queuedResults, type LeaderboardEntry } from './scores'
import './Leaderboard.css'

/** Weekly and monthly boards, ranked on the best single haul.
 *
 *  Reads fine while signed out - a board nobody can look at isn't much of a
 *  board - and says so plainly when there's nothing to show yet rather than
 *  rendering an empty table. */
export default function Leaderboard() {
  const [period, setPeriod] = useState<'week' | 'month'>('week')
  // Held together with the period they belong to, so switching tabs shows
  // "loading" by simple comparison rather than by clearing state during
  // render - which is what the purity rule is there to prevent.
  const [loaded, setLoaded] = useState<{
    period: 'week' | 'month'
    entries: LeaderboardEntry[] | null
  } | null>(null)
  const [pending, setPending] = useState(0)

  useEffect(() => {
    let cancelled = false
    getLeaderboard(period)
      .then((data) => {
        if (!cancelled) setLoaded({ period, entries: data.entries })
      })
      .catch(() => {
        // entries: null distinguishes "failed" from "loaded but empty".
        if (!cancelled) setLoaded({ period, entries: null })
      })
    return () => {
      cancelled = true
    }
  }, [period])

  const current = loaded?.period === period ? loaded : null
  const entries = current?.entries
  const failed = current != null && current.entries === null

  // Runs finished offline haven't reached the board yet; showing the count
  // explains why someone's best haul isn't listed.
  useEffect(() => {
    const update = () => setPending(queuedResults().length)
    update()
    window.addEventListener('online', update)
    return () => window.removeEventListener('online', update)
  }, [])

  return (
    <section className="lb">
      <header className="lb-head">
        <h2 className="lb-title">Leaderboard</h2>
        <div className="lb-tabs" role="tablist">
          {(['week', 'month'] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={period === value}
              className={`lb-tab ${period === value ? 'is-active' : ''}`}
              onClick={() => setPeriod(value)}
            >
              {value === 'week' ? 'This week' : 'This month'}
            </button>
          ))}
        </div>
      </header>

      {pending > 0 && (
        <p className="lb-pending">
          {pending} run{pending === 1 ? '' : 's'} waiting to upload — they'll appear once you're
          back online.
        </p>
      )}

      {failed ? (
        <p className="lb-empty">Couldn&apos;t load the board. You may be offline.</p>
      ) : entries == null ? (
        <p className="lb-empty">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="lb-empty">No hauls logged yet this {period}. Be the first.</p>
      ) : (
        <ol className="lb-list">
          {entries.map((entry) => (
            <li key={`${entry.rank}-${entry.name}`} className="lb-row">
              <span className="lb-rank">{entry.rank}</span>
              <span className="lb-name">{entry.name}</span>
              <span className="lb-detail">
                {entry.delivered} delivered{entry.lost > 0 ? `, ${entry.lost} lost` : ''}
              </span>
              <span className="lb-payout">${entry.payout.toLocaleString('en-US')}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
