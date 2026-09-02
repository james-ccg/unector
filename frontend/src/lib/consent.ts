/**
 * Consent for the browser storage this app uses.
 *
 * Freight Pilot has no analytics, no advertising, and no third-party
 * trackers, so the usual cookie-banner categories mostly don't apply. What it
 * does store is listed honestly below, and the two optional groups genuinely
 * do nothing until someone opts in - the switches are not decorative.
 *
 * The consent record itself is written without consent. Storing "this person
 * declined" is what makes the decision stick, and re-asking on every page
 * because the answer couldn't be saved would be worse for the visitor than
 * the single key it costs.
 */

const CONSENT_KEY = 'fp-consent'
const CONSENT_VERSION = 1

export type ConsentCategory = 'preferences' | 'game'

export interface ConsentRecord {
  version: number
  /** Appearance, interface font, reduced motion. */
  preferences: boolean
  /** Game tickets and the offline score queue. */
  game: boolean
  decidedAt: string
}

/** Keys grouped by what they're for, so the banner can describe them
 *  accurately and revoking consent can actually clear them. */
export const STORAGE_BY_CATEGORY: Record<ConsentCategory, string[]> = {
  preferences: ['fp-theme', 'fp-font', 'fp-reduce-motion'],
  game: ['fp-game-tickets', 'fp-game-queue'],
}

/** Set by the server as a direct result of signing in with Google, and only
 *  then. Not in ESSENTIAL_STORAGE because the site works perfectly well
 *  without it - it saves picking your own address off Google's list - and
 *  not an opt-in category either, because nothing on the page can read or
 *  write it: it is httpOnly, so the browser sends it to the server and
 *  shows it to no one. "Use a different account" on the login page clears
 *  it, and it expires by itself after 30 days. Listed because this app
 *  names everything it stores. */
export const SIGN_IN_STORAGE = [
  {
    name: 'fp_last_account',
    purpose:
      'Remembers which Google account signed in here last, so returning after signing out takes one click. Expires after 30 days.',
  },
]

/** Storage that works without asking, because the site can't do its job
 *  without it. Listed so the privacy page and the banner can name it rather
 *  than gesturing at "essential cookies". */
export const ESSENTIAL_STORAGE = [
  { name: 'fp_session', purpose: 'Keeps you signed in. Set by the server and not readable by page scripts.' },
  { name: 'fp_csrf', purpose: 'Stops other sites making requests as you.' },
  { name: 'fp-register-plan', purpose: 'Carries the plan you picked through signup.' },
  { name: 'fp-consent', purpose: 'Remembers this choice, so you are not asked again.' },
]

function readRaw(): ConsentRecord | null {
  try {
    const raw = localStorage.getItem(CONSENT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as ConsentRecord
    // A changed version means the categories have changed, so the old answer
    // no longer covers what's being asked - treat it as undecided.
    return parsed.version === CONSENT_VERSION ? parsed : null
  } catch {
    return null
  }
}

export function getConsent(): ConsentRecord | null {
  return readRaw()
}

export function hasDecided(): boolean {
  return readRaw() !== null
}

/** The gate every optional write goes through. Undecided counts as "no". */
export function allows(category: ConsentCategory): boolean {
  return readRaw()?.[category] === true
}

export function saveConsent(choice: Record<ConsentCategory, boolean>): ConsentRecord {
  const record: ConsentRecord = {
    version: CONSENT_VERSION,
    preferences: choice.preferences,
    game: choice.game,
    decidedAt: new Date().toISOString(),
  }
  try {
    localStorage.setItem(CONSENT_KEY, JSON.stringify(record))
  } catch {
    // Nothing more to do - the choice holds for this tab either way.
  }
  // Withdrawing consent has to actually remove what was stored under it, or
  // the switch is a lie.
  for (const category of ['preferences', 'game'] as ConsentCategory[]) {
    if (!record[category]) clearCategory(category)
  }
  window.dispatchEvent(new CustomEvent('fp:consent-changed'))
  return record
}

export function clearCategory(category: ConsentCategory) {
  for (const key of STORAGE_BY_CATEGORY[category]) {
    try {
      localStorage.removeItem(key)
    } catch {
      // Storage unavailable - there was nothing persisted to clear.
    }
  }
}

/** Wraps a localStorage write in its consent check. */
export function storeIfAllowed(category: ConsentCategory, key: string, value: string) {
  if (!allows(category)) return
  try {
    localStorage.setItem(key, value)
  } catch {
    // Private window or blocked storage.
  }
}

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
