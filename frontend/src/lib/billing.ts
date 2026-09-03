/**
 * The facts about a trial, a card and a plan that the app has to state in
 * more than one place, kept together so they cannot drift apart.
 *
 * A trial that becomes a paid plan is a negative-option offer. ROSCA still
 * requires the material terms to be disclosed clearly before billing
 * details are taken, and state auto-renewal laws - California's is the
 * strictest - want the same terms plus a plain way to cancel. So the
 * wording built from here always carries the four things that matter:
 * that it renews by itself, when, how much, and how to stop it.
 */

/** Matches `trial_period_days` in services/stripe_service.py. */
export const TRIAL_DAYS = 7

/**
 * Statuses where the money for the current period has not actually been
 * taken - a trial that has not converted, a first payment that never
 * succeeded, a failed renewal, or a plan paused for want of a card.
 *
 * Mirrors UNPAID_STATUSES in services/stripe_service.py, which is what
 * actually enforces this. Repeated here so the button can say so before it
 * is pressed, rather than the server refusing afterwards.
 */
export const UNPAID_STATUSES = [
  'trialing',
  'incomplete',
  'past_due',
  'unpaid',
  'paused',
]

/** True while the current period is still unpaid, so the last card stays. */
export function isAwaitingPayment(status: string | null | undefined): boolean {
  return !!status && UNPAID_STATUSES.includes(status)
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
 * Why the last payment method cannot come off yet. Says the condition
 * rather than "no", so it reads as something that ends rather than a trap.
 *
 * Deliberately not "card": Stripe Checkout offers whatever is enabled on
 * the account - PayPal, wallets, Link - and the rule is about the last
 * method of any kind, not about cards.
 */
export const CARD_HELD_NOTICE =
  "This is the only payment method on a plan that hasn't been paid for yet, so it can't be " +
  'removed right now. Add a second one to replace it, or cancel the plan from Manage billing. ' +
  'Once the first payment goes through, you can take it off whenever you like.'

/**
 * What removing the last payment method does once the plan is paid up. Not
 * a refusal - it is allowed - but it ends the plan, so it is said before
 * the click rather than discovered in an email later.
 */
export const CARD_REMOVAL_ENDS_PLAN_NOTICE =
  'Removing your only payment method ends the plan when the period you have paid for runs ' +
  'out. You keep everything until then, and nothing is charged again.'

/**
 * How to name a saved method in the UI. Stripe gives a card a brand and
 * four digits; PayPal and the wallets have neither, and "paypal" in lower
 * case looks like a bug rather than a choice.
 */
export const METHOD_LABELS: Record<string, string> = {
  card: 'Card',
  paypal: 'PayPal',
  link: 'Link',
  cashapp: 'Cash App Pay',
  us_bank_account: 'Bank account',
  amazon_pay: 'Amazon Pay',
}

export function methodLabel(type: string, brand: string | null): string {
  if (brand) return `${brand[0].toUpperCase()}${brand.slice(1)}`
  return METHOD_LABELS[type] ?? type.replace(/_/g, ' ')
}
