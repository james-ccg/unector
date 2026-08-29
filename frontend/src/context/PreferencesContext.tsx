import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { MotionConfig } from 'motion/react'

export type FontChoice = 'default' | 'system' | 'serif'

const FONT_KEY = 'fp-font'
const REDUCE_MOTION_KEY = 'fp-reduce-motion'

// Storage can throw outright, not just come back empty - a private window or
// a browser set to block site data - so every read/write here is guarded.
function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Non-fatal - the choice just won't outlive this tab.
  }
}

function readStoredFont(): FontChoice {
  const stored = readStored(FONT_KEY)
  return stored === 'system' || stored === 'serif' || stored === 'default' ? stored : 'default'
}

// No stored preference yet -> default to the OS-level accessibility setting,
// same first-run behavior as Appearance defaulting to "system".
function readStoredReduceMotion(): boolean {
  const stored = readStored(REDUCE_MOTION_KEY)
  if (stored === 'true') return true
  if (stored === 'false') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function applyFont(font: FontChoice) {
  // "default" removes the attribute - index.css only defines overrides for
  // the non-default cases, so this falls back to the brand face.
  if (font === 'default') {
    document.documentElement.removeAttribute('data-font')
  } else {
    document.documentElement.setAttribute('data-font', font)
  }
}

function applyReduceMotion(reduce: boolean) {
  document.documentElement.setAttribute('data-reduce-motion', String(reduce))
}

interface PreferencesContextValue {
  font: FontChoice
  setFont: (font: FontChoice) => void
  reduceMotion: boolean
  setReduceMotion: (reduce: boolean) => void
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null)

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [font, setFontState] = useState<FontChoice>(readStoredFont)
  const [reduceMotion, setReduceMotionState] = useState<boolean>(readStoredReduceMotion)

  // Re-stamp on mount so React stays the source of truth for these
  // attributes, the same way ThemeProvider does - index.html's bootstrap
  // sets them first, and without this nothing would ever reconcile the two.
  useEffect(() => {
    applyFont(font)
    applyReduceMotion(reduceMotion)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setFont = (next: FontChoice) => {
    setFontState(next)
    applyFont(next)
    writeStored(FONT_KEY, next)
  }

  const setReduceMotion = (reduce: boolean) => {
    setReduceMotionState(reduce)
    applyReduceMotion(reduce)
    writeStored(REDUCE_MOTION_KEY, String(reduce))
  }

  return (
    <PreferencesContext.Provider value={{ font, setFont, reduceMotion, setReduceMotion }}>
      {/* "always" hard-disables transform/layout animations for every motion.*
         component in the tree (our explicit override); "user" falls back to
         following the OS prefers-reduced-motion setting live, same as any
         visitor who never touched this toggle. Non-motion CSS transitions
         (hover states, ThemeToggle, etc.) are handled separately in
         index.css via the [data-reduce-motion] attribute set above. */}
      <MotionConfig reducedMotion={reduceMotion ? 'always' : 'user'}>
        {children}
      </MotionConfig>
    </PreferencesContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- see AuthContext.tsx's identical pattern/comment.
export function usePreferences(): PreferencesContextValue {
  const ctx = useContext(PreferencesContext)
  if (!ctx) throw new Error('usePreferences must be used within a PreferencesProvider')
  return ctx
}
