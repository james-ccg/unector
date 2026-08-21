import { createContext, useContext, useState, type ReactNode } from 'react'
import { MotionConfig } from 'motion/react'

export type FontSize = 'small' | 'medium' | 'large'

const FONT_SIZE_KEY = 'fp-font-size'
const REDUCE_MOTION_KEY = 'fp-reduce-motion'

function readStoredFontSize(): FontSize {
  const stored = localStorage.getItem(FONT_SIZE_KEY)
  return stored === 'small' || stored === 'medium' || stored === 'large' ? stored : 'medium'
}

// No stored preference yet -> default to the OS-level accessibility setting,
// same first-run behavior as Appearance defaulting to "system".
function readStoredReduceMotion(): boolean {
  const stored = localStorage.getItem(REDUCE_MOTION_KEY)
  if (stored === 'true') return true
  if (stored === 'false') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function applyFontSize(size: FontSize) {
  // "medium" removes the attribute - index.css only defines zoom rules for
  // the small/large cases, so this is the implicit 1x default.
  if (size === 'medium') {
    document.documentElement.removeAttribute('data-font-size')
  } else {
    document.documentElement.setAttribute('data-font-size', size)
  }
}

function applyReduceMotion(reduce: boolean) {
  document.documentElement.setAttribute('data-reduce-motion', String(reduce))
}

interface PreferencesContextValue {
  fontSize: FontSize
  setFontSize: (size: FontSize) => void
  reduceMotion: boolean
  setReduceMotion: (reduce: boolean) => void
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null)

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [fontSize, setFontSizeState] = useState<FontSize>(readStoredFontSize)
  const [reduceMotion, setReduceMotionState] = useState<boolean>(readStoredReduceMotion)

  const setFontSize = (size: FontSize) => {
    setFontSizeState(size)
    localStorage.setItem(FONT_SIZE_KEY, size)
    applyFontSize(size)
  }

  const setReduceMotion = (reduce: boolean) => {
    setReduceMotionState(reduce)
    localStorage.setItem(REDUCE_MOTION_KEY, String(reduce))
    applyReduceMotion(reduce)
  }

  return (
    <PreferencesContext.Provider value={{ fontSize, setFontSize, reduceMotion, setReduceMotion }}>
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
