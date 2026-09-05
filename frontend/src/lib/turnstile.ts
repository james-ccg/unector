/** Turning a Turnstile failure into something somebody can act on.
 *
 * Kept out of the component so the component stays a component - and because
 * the wording is shared by the three pages that gate on the check, which is
 * the kind of sentence that otherwise ends up written three different ways.
 */

/** Why a Turnstile error code happened, in words.
 *
 * The codes are Cloudflare's; these are the ones a real deployment hits.
 * 110200 is the one that costs the most time to work out unaided - the widget
 * draws a generic "cannot connect" box, and the actual problem is that the
 * hostname is not on the site key's allowed list. That is a setting in the
 * Cloudflare dashboard, so no amount of retrying changes it, and the box
 * gives no hint in that direction.
 */
const ERROR_REASONS: Record<string, string> = {
  '110200': 'this domain is not on the allowed list for the bot check',
  '110100': 'the site key is not valid',
  '110110': 'the site key is not valid for this domain',
  '106020': 'the bot check could not verify the browser',
}

export function describeTurnstileError(code: string): string {
  for (const [prefix, reason] of Object.entries(ERROR_REASONS)) {
    if (code.startsWith(prefix)) return reason
  }
  if (code.startsWith('300') || code.startsWith('600')) {
    return 'the bot check ran into an internal error'
  }
  return `the bot check reported error ${code}`
}

/** The message a form shows when the check cannot run.
 *
 * The important half is the last sentence. The submit button is already
 * disabled without a token, so the reader is looking at a form that will not
 * submit; telling them to try again would be telling them to do the one
 * thing that cannot work.
 */
export function turnstileUnavailableMessage(reason: string): string {
  return (
    `The bot check couldn't run - ${reason}. Signing in needs it, so trying again ` +
    "won't help; use a different network, or open the dashboard on its usual address."
  )
}
