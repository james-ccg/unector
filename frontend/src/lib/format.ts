// Number formatting for money and counts.
//
// Everything here is pinned to en-US on purpose. A bare toLocaleString()
// follows the BROWSER's locale, so the same $10,400 rendered as "10 400" on
// a ru/uz-locale machine and "10.400" on a de one - three different figures
// for one number. Unector's amounts are US dollars against US rate
// confirmations, so the separator is part of the data's format, not a
// per-viewer preference.

const US_NUMBER = new Intl.NumberFormat('en-US')

const US_MONEY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

/** 10400 -> "10,400" */
export function formatCount(value: number): string {
  return US_NUMBER.format(value)
}

/** 10400 -> "$10,400". Rounded: cents are noise on a rate figure. */
export function formatMoney(value: number | null | undefined): string {
  return US_MONEY.format(Math.round(value || 0))
}
