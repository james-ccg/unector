// Display strings for subscription_tier values. Keep in sync with
// PLAN_LIMITS/PLAN_PRICES in config.py - those are the source of truth for
// what each tier actually allows/costs; this is just presentation.
export const PLAN_LABELS: Record<string, string> = {
  free: 'Free',
  pro: 'Pro',
  max_5x: 'Max 5x',
  max_20x: 'Max 20x',
}

export const PLAN_PRICE_LABELS: Record<string, string> = {
  free: '$0',
  pro: '$20/mo',
  max_5x: '$100/mo',
  max_20x: '$200/mo',
}
