/** Turns the `?gmail=...` flag on an OAuth callback redirect into a sentence.
 *
 * The backend used to redirect with a single `?gmail=error` for four
 * unrelated failures, so all three pages that read this flag could only say
 * "Something went wrong connecting Gmail" - including when the owner had
 * pressed Cancel on Google's own consent screen, which is not a fault at
 * all. Each failure now arrives with its own code, and the sentence names
 * it so a screenshot of the banner is enough to tell them apart.
 */

const REVOKE_STEPS =
  "Go to myaccount.google.com/permissions, remove Unector's access there, then try again."

const MESSAGES: Record<string, string> = {
  error_no_refresh_token:
    "Google didn't grant lasting access this time - this usually happens if you've connected this " +
    `same account before. ${REVOKE_STEPS}`,
  error_expired_link:
    'That connection link had expired by the time Google sent you back. Start the connection again ' +
    '- the new link is good for a few minutes.',
  error_incomplete:
    'Google sent you back without the code needed to finish the connection. Try again.',
  error_exchange:
    'Google approved the connection but the final step failed on our side. Try again - if it keeps ' +
    'happening, the problem is ours, not yours.',
}

/** Google's own error codes, which arrive as `?gmail=error_google&reason=`. */
const GOOGLE_REASONS: Record<string, string> = {
  access_denied: 'The connection was cancelled on the Google screen, so nothing was connected.',
  admin_policy_enforced:
    "Your Google Workspace administrator blocks this connection. They'll need to allow it first.",
  invalid_scope: 'Google rejected the permissions this app asked for. That is a bug on our side.',
  org_internal: 'That Google account is outside the organisation this app is allowed to connect to.',
}

/** `null` when the flag is a success or something we don't recognise as a
 *  failure, so callers can keep treating it as "nothing to show". */
export function gmailErrorMessage(status: string | null, reason?: string | null): string | null {
  if (!status || status === 'connected') return null

  if (status === 'error_google') {
    const known = reason ? GOOGLE_REASONS[reason] : null
    if (known) return known
    return reason
      ? `Google refused the connection (${reason}).`
      : 'Google refused the connection.'
  }

  const known = MESSAGES[status]
  if (known) return known

  // Still names it. An unrecognised code is worth showing verbatim - it is
  // the only clue anyone will have.
  return `Connecting Gmail failed (${status}).`
}
