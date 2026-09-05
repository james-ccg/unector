import { useEffect, useRef } from 'react'
import { describeTurnstileError } from '../lib/turnstile'

// Cloudflare Turnstile's own script attaches itself here - not bundled,
// since it has to be served from Cloudflare to do its job.
declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: Record<string, unknown>) => string
      reset: (widgetId?: string) => void
      remove: (widgetId?: string) => void
    }
  }
}

let scriptPromise: Promise<void> | null = null
function loadTurnstileScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  if (!scriptPromise) {
    scriptPromise = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
      script.async = true
      script.defer = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('the script could not be reached'))
      document.head.appendChild(script)
    }).catch((err) => {
      // A rejected promise stays rejected, so caching this one meant the
      // first failure was permanent: every later mount reused it and never
      // tried again, on a connection that may since have come back.
      scriptPromise = null
      throw err
    })
  }
  return scriptPromise
}

interface TurnstileProps {
  siteKey: string | null
  onToken: (token: string | null) => void
  /** Called when the widget cannot produce a token at all, with a reason.
   *
   *  Without this the failure was invisible to the app: the token stayed
   *  null, the form submitted anyway, and the server answered "Couldn't
   *  confirm you're not a bot. Try again." - which describes a different
   *  problem and suggests the one thing that will not help. */
  onUnavailable?: (reason: string) => void
}

// Renders nothing (and forms just submit without a token) until a site key
// is configured in .env - see GET /api/public/config.
export default function Turnstile({ siteKey, onToken, onUnavailable }: TurnstileProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | undefined>(undefined)
  // Held in a ref so a parent that passes an inline arrow function does not
  // re-run the effect - remounting the widget on every render would make it
  // issue a fresh challenge each time.
  const onUnavailableRef = useRef(onUnavailable)
  useEffect(() => {
    onUnavailableRef.current = onUnavailable
  }, [onUnavailable])

  useEffect(() => {
    if (!siteKey) return
    let cancelled = false

    loadTurnstileScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.turnstile) return
        widgetIdRef.current = window.turnstile.render(containerRef.current, {
          sitekey: siteKey,
          callback: (token: string) => onToken(token),
          'expired-callback': () => onToken(null),
          'error-callback': (code?: string) => {
            onToken(null)
            if (!cancelled) {
              onUnavailableRef.current?.(describeTurnstileError(String(code ?? 'unknown')))
            }
            // Falsy, so Turnstile still draws its own box. It says roughly
            // the same thing, and two explanations beat one that the reader
            // has to guess is related to the empty space above it.
            return false
          },
        })
      })
      .catch((err: unknown) => {
        // Was an unhandled rejection: the message written for this case was
        // never shown to anybody, and the console got a warning instead.
        if (cancelled) return
        const detail = err instanceof Error ? err.message : 'it could not be loaded'
        onToken(null)
        onUnavailableRef.current?.(detail)
      })

    return () => {
      cancelled = true
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteKey])

  if (!siteKey) return null
  return <div ref={containerRef} className="turnstile-widget" />
}
