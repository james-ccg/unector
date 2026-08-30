import type { ReactNode } from 'react'
import Icon from './Icon'
import './Alert.css'

export type AlertKind = 'success' | 'error' | 'warning' | 'info'

const ICONS: Record<AlertKind, Parameters<typeof Icon>[0]['name']> = {
  success: 'check',
  error: 'warning',
  warning: 'warning',
  info: 'monitor',
}

const ROLES: Record<AlertKind, 'alert' | 'status'> = {
  // An error interrupts what someone was doing, so it's announced
  // immediately; the rest are progress reports and shouldn't cut across
  // whatever a screen reader is already saying.
  error: 'alert',
  warning: 'alert',
  success: 'status',
  info: 'status',
}

interface AlertProps {
  kind: AlertKind
  children: ReactNode
  /** Omit to make the alert non-dismissable - correct for a condition the
   *  user has to actually resolve, like a dead Gmail connection. */
  onDismiss?: () => void
  className?: string
}

/** The one inline message component.
 *
 * These styles used to be split across two page stylesheets - `.banner` in
 * DashboardPage.css and `.banner-close` in SettingsPage.css - with
 * TwoFactorSettings importing neither and rendering correctly only because
 * it happens to be mounted inside Settings, which pulls in both. Anywhere
 * else it would have lost its dismiss button's styling. Keeping the markup
 * and the CSS together makes it safe to use on any page. */
export default function Alert({ kind, children, onDismiss, className = '' }: AlertProps) {
  return (
    <div className={`alert alert-${kind} ${className}`} role={ROLES[kind]}>
      <Icon name={ICONS[kind]} size={16} />
      <div className="alert-body">{children}</div>
      {onDismiss && (
        <button type="button" className="alert-close" onClick={onDismiss} aria-label="Dismiss">
          <Icon name="close" size={14} />
        </button>
      )}
    </div>
  )
}
