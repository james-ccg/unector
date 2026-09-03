/**
 * The facts about a trial and a saved card that the app has to state in
 * more than one place, kept in one place so they cannot drift apart.
 *
 * A trial that turns into a charge is a negative-option offer. ROSCA still
 * requires the material terms to be disclosed clearly before billing
 * details are taken, and state auto-renewal laws - California's is the
 * strictest - want the same terms plus a plain way to cancel. So the
 * wording built from here always carries the four things that matter:
 * that it renews by itself, when, how much, and how to stop it.
 */

/** Matches `trial_period_days` in services/stripe_service.py. */
export const TRIAL_DAYS = 7

/**
 * The statuses Stripe calls live, and the reason a card cannot be taken
 * off while one of them holds.
 *
 * This mirrors the guard in services/stripe_service.py's
 * detach_payment_method - the server is what enforces it. Repeated here so
 * the person is told before they click, rather than by an error afterwards.
 */
export const LIVE_SUBSCRIPTION_STATUSES = [
  'active',
  'trialing',
  'past_due',
  'unpaid',
  'paused',
]

export function isSubscriptionLive(status: string | null | undefined): boolean {
  return !!status && LIVE_SUBSCRIPTION_STATUSES.includes(status)
}

/** Dollars per interval. Keep in sync with PLAN_PRICES in config.py. */
export const PLAN_AMOUNTS: Record<string, { month: number; year: number }> = {
  pro: { month: 20, year: 200 },
  max_5x: { month: 100, year: 1000 },
  max_20x: { month: 200, year: 2000 },
}

/**
 * What will actually be charged, in words - "$20 a month".
 *
 * Returns null for a plan with no price rather than guessing one. Callers
 * fall back to wording that does not name a figure, because a wrong number
 * here is worse than no number.
 */
export function chargeLabel(
  tier: string,
  interval: 'month' | 'year' | null | undefined,
): string | null {
  const amounts = PLAN_AMOUNTS[tier]
  if (!amounts) return null
  const period = interval === 'year' ? 'year' : 'month'
  return `$${amounts[period]} a ${period}`
}

/**
 * The one-line notice for a card that is on file under a live
 * subscription. Says why it is held and both ways out, so it reads as a
 * consequence of subscribing rather than as a trap.
 */
export const CARD_HELD_NOTICE =
  "While a plan or trial is running, the last card on file can't be removed - " +
  'add another card to replace it, or cancel the plan first from Manage billing.'
