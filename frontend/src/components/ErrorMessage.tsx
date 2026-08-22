import { Link } from 'react-router-dom'

const UPGRADE_PHRASE = 'Upgrade your plan'

/**
 * Renders an error string as-is, except the plan-limit errors from
 * miniapp/api.py's driver-cap checks (update_subscription/add_driver),
 * which always end in "...Upgrade your plan to ...". Backend error
 * details are plain text, so this is the one place that phrase becomes an
 * actual link to Pricing instead of dead text.
 */
export default function ErrorMessage({ text, className }: { text: string; className?: string }) {
  const index = text.indexOf(UPGRADE_PHRASE)
  if (index === -1) {
    return <p className={className}>{text}</p>
  }

  const before = text.slice(0, index)
  const after = text.slice(index + UPGRADE_PHRASE.length)
  return (
    <p className={className}>
      {before}
      <Link to="/pages/pricing">{UPGRADE_PHRASE}</Link>
      {after}
    </p>
  )
}
