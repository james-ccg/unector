import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'fp-theme'

// "Auto" (preference === 'system') follows the device's setting, and only
// that. It used to also flip to dark after 7pm on a device that hadn't
// asked for it, which meant simply reloading the page in the evening
// changed the theme out from under you - surprising on its own, and
// indistinguishable from a bug when it happened. Auto now means what it
// says everywhere else: mirror the OS.
function resolveTheme(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return preference
}

function applyTheme(preference: ThemePreference) {
  // Auto stamps its current resolution as an explicit data-theme rather than
  // clearing the attribute and leaning on index.css's prefers-color-scheme
  // block. Both would render the same thing, but keeping the attribute
  // always present means resolvedTheme (which components read) can never
  // disagree with what's actually on screen. index.html's anti-flash script
  // mirrors this for the instant before React mounts.
  document.documentElement.setAttribute('data-theme', resolveTheme(preference))
}

interface ThemeContextValue {
  preference: ThemePreference
  resolvedTheme: 'light' | 'dark'
  setPreference: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStoredPreference(): ThemePreference {
  // Storage can throw outright, not just come back empty - a private window
  // or a browser set to block site data. Falling back to Auto is correct
  // there; letting it throw would take the whole provider down.
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference)
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() => resolveTheme(preference))

  // Re-stamp on mount so React is the single source of truth for data-theme.
  // index.html's anti-flash script sets it first, but nothing here ever
  // re-applied it afterwards - so any disagreement between the two (storage
  // that reads back empty, a write that silently failed) left the page
  // showing one theme while Settings showed another, with no way to
  // self-correct. resolvedTheme is already right from its own initializer;
  // this effect only pushes that resolution out to the DOM.
  useEffect(() => {
    applyTheme(preference)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setPreference = (next: ThemePreference) => {
    setPreferenceState(next)
    // Applied BEFORE persisting: if storage throws, the theme the user just
    // picked must still take effect for this session rather than the click
    // appearing to do nothing.
    applyTheme(next)
    setResolvedTheme(resolveTheme(next))
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Non-fatal - the choice just won't outlive this tab.
    }
  }

  // On "auto", follow the OS live while the tab stays open. This used to
  // also poll on a 5-minute timer, purely so the retired time-of-day rule
  // could take effect mid-session; with Auto now meaning "mirror the OS",
  // the media query's own change event is the only signal there is.
  useEffect(() => {
    if (preference !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      applyTheme('system')
      setResolvedTheme(resolveTheme('system'))
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [preference])

  return (
    <ThemeContext.Provider value={{ preference, resolvedTheme, setPreference }}>
      {children}
    </ThemeContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- see AuthContext.tsx's identical pattern/comment.
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
