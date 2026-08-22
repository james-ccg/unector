import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'fp-theme'

// "Auto" (preference === 'system') follows the device's setting, but also
// leans dark late at night even on a device that doesn't say so (e.g. no
// prefers-color-scheme support, or a desktop left on "light" that nobody's
// going to change just for one evening session). The device preference
// still wins whenever it actively says dark - night hours only ever push
// TOWARD dark, never override an explicit light-during-the-day signal from
// a device that actually supports the media query and prefers light while
// it's dark out for the user (unusual, but the device's stated preference
// is still the stronger signal of the two).
const NIGHT_START_HOUR = 19 // 7pm
const NIGHT_END_HOUR = 7 // 7am

function isLocalNightTime(): boolean {
  const hour = new Date().getHours()
  return hour >= NIGHT_START_HOUR || hour < NIGHT_END_HOUR
}

function resolveTheme(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    if (media.matches) return 'dark'
    // matchMedia can't distinguish "device actively prefers light" from "no
    // preference is exposed at all" - media.matches on the dark query being
    // false covers both, so time is free to weigh in either way here.
    return isLocalNightTime() ? 'dark' : 'light'
  }
  return preference
}

function applyTheme(preference: ThemePreference) {
  // "system"/Auto stamps its CURRENT resolution (system preference, falling
  // back to the time-of-day rule) as an explicit data-theme - it can't just
  // remove the attribute and lean on index.css's prefers-color-scheme
  // media query the way a pure system-only toggle could, since that query
  // has no way to know it's nighttime. index.html's anti-flash script
  // mirrors this same resolution for the instant before React mounts.
  document.documentElement.setAttribute('data-theme', preference === 'system' ? resolveTheme('system') : preference)
}

interface ThemeContextValue {
  preference: ThemePreference
  resolvedTheme: 'light' | 'dark'
  setPreference: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
  })
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() => resolveTheme(preference))

  const setPreference = (next: ThemePreference) => {
    setPreferenceState(next)
    localStorage.setItem(STORAGE_KEY, next)
    applyTheme(next)
    setResolvedTheme(resolveTheme(next))
  }

  // If the user is on "auto", re-resolve live while the tab stays open -
  // both when the OS theme changes (e.g. switches to dark mode at sunset)
  // and, separately, when the clock crosses the night/day boundary this
  // module's own time-of-day rule uses.
  useEffect(() => {
    if (preference !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      applyTheme('system')
      setResolvedTheme(resolveTheme('system'))
    }
    media.addEventListener('change', onChange)
    const interval = window.setInterval(onChange, 5 * 60 * 1000)
    return () => {
      media.removeEventListener('change', onChange)
      window.clearInterval(interval)
    }
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
