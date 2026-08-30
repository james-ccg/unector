import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ESSENTIAL_STORAGE, hasDecided, saveConsent, getConsent, type ConsentCategory,
} from '../lib/consent'
import './CookieConsent.css'

/**
 * Storage consent.
 *
 * Accept and Reject carry the same visual weight on purpose - a prominent
 * "Accept all" beside a greyed-out "Reject" is the pattern regulators
 * single out, because a choice that is harder to decline isn't freely given.
 * Declining is one click from the banner, not buried behind a settings
 * panel.
 *
 * The categories are the real ones. This app has no analytics and no
 * advertising, so it doesn't list them; inventing categories to look
 * thorough would misrepresent what's actually stored.
 */

const CATEGORIES: {
  key: ConsentCategory
  label: string
  detail: string
}[] = [
  {
    key: 'preferences',
    label: 'Appearance',
    detail: 'Remembers your theme, interface font, and reduced-motion setting between visits. Decline and the app still respects your device settings, it just won’t remember changes you make here.',
  },
  {
    key: 'game',
    label: 'Truck game',
    detail: 'Stores play tickets and any scores finished offline, so they can be uploaded when you reconnect. Only used on the /play page.',
  },
]

export default function CookieConsent() {
  // Read once in the initializer rather than in a mount effect: this reads
  // storage, which is impure, and doing it during an effect would both trip
  // the purity rule and flash the banner for a frame at people who have
  // already answered.
  const [open, setOpen] = useState(() => !hasDecided())
  const [showDetail, setShowDetail] = useState(false)
  const [choice, setChoice] = useState<Record<ConsentCategory, boolean>>(() => {
    const existing = getConsent()
    return existing
      ? { preferences: existing.preferences, game: existing.game }
      : { preferences: false, game: false }
  })

  // Lets Settings (or anywhere else) reopen this so a decision can be
  // changed later - consent has to be as easy to withdraw as it was to give.
  useEffect(() => {
    const reopen = () => {
      const existing = getConsent()
      if (existing) setChoice({ preferences: existing.preferences, game: existing.game })
      setShowDetail(true)
      setOpen(true)
    }
    window.addEventListener('fp:open-consent', reopen)
    return () => window.removeEventListener('fp:open-consent', reopen)
  }, [])

  const decide = (record: Record<ConsentCategory, boolean>) => {
    saveConsent(record)
    setOpen(false)
    setShowDetail(false)
  }

  if (!open) return null

  return (
    <div className="consent" role="dialog" aria-label="Storage preferences" aria-modal="false">
      <div className="consent-inner">
        <div className="consent-copy">
          <p className="consent-title">A note on what we store</p>
          <p className="consent-text">
            Freight Pilot keeps you signed in with a session cookie, which it needs to work at all.
            Beyond that it stores only your appearance settings and, if you play it, the truck
            game. <strong>No analytics, no advertising, no third-party trackers.</strong>{' '}
            <Link to="/pages/privacy">Read the privacy policy</Link>.
          </p>
        </div>

        {showDetail && (
          <div className="consent-detail">
            <div className="consent-row is-locked">
              <div>
                <p className="consent-row-label">Essential</p>
                <p className="consent-row-detail">
                  {ESSENTIAL_STORAGE.map((item) => item.name).join(', ')} &mdash; signing in, security,
                  and remembering this choice. Always on, because the site can&apos;t work without them.
                </p>
              </div>
              <span className="consent-locked-tag">Required</span>
            </div>

            {CATEGORIES.map((category) => (
              <div className="consent-row" key={category.key}>
                <div>
                  <p className="consent-row-label">{category.label}</p>
                  <p className="consent-row-detail">{category.detail}</p>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={choice[category.key]}
                    onChange={(e) =>
                      setChoice((prev) => ({ ...prev, [category.key]: e.target.checked }))
                    }
                    aria-label={category.label}
                  />
                  <span className="switch-track"><span className="switch-thumb" /></span>
                </label>
              </div>
            ))}
          </div>
        )}

        <div className="consent-actions">
          {showDetail ? (
            <button type="button" className="btn btn-primary" onClick={() => decide(choice)}>
              Save choices
            </button>
          ) : (
            <button type="button" className="btn btn-ghost" onClick={() => setShowDetail(true)}>
              Choose what to store
            </button>
          )}
          {/* Same size, same styling, same prominence as Accept. */}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => decide({ preferences: false, game: false })}
          >
            Essential only
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => decide({ preferences: true, game: true })}
          >
            Accept all
          </button>
        </div>
      </div>
    </div>
  )
}
