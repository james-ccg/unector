import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'motion/react'
import { useAuth } from '../context/AuthContext'
import { authApi, errorMessage } from '../services/api'
import Icon from './Icon'
import '../pages/DashboardPage.css'
import './EditStatusModal.css'

/** One-click statuses.
 *
 * The single biggest thing a status picker can do is stop making people
 * write anything at all - the same handful of statuses get typed over and
 * over, so each of these sets the emoji, the words and the expiry together.
 * These are dispatch statuses, not office ones: what a dispatcher actually
 * needs to know is where the truck is in its day.
 */
const SUGGESTIONS: { emoji: string; text: string; minutes: number | null }[] = [
  { emoji: '🚚', text: 'On the road', minutes: null },
  { emoji: '📦', text: 'At pickup', minutes: 4 * 60 },
  { emoji: '🏭', text: 'At delivery', minutes: 4 * 60 },
  { emoji: '😴', text: 'Off duty', minutes: 10 * 60 },
  { emoji: '🔧', text: 'In the shop', minutes: 24 * 60 },
  { emoji: '🏠', text: 'Home time', minutes: 7 * 24 * 60 },
]

const EMOJI_PRESETS = ['🚚', '📦', '🏭', '😴', '🔧', '🏠', '⛽', '🅿️', '🌧️', '🚧', '📞', '☕']

const DURATIONS: { label: string; minutes: number | null }[] = [
  { label: "Don't clear", minutes: null },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '4 hours', minutes: 240 },
  { label: '10 hours', minutes: 600 },
  { label: 'Today', minutes: 24 * 60 },
  { label: 'This week', minutes: 7 * 24 * 60 },
]

/** "clears at 6:40 PM" - a duration is easier to pick, but a time is what
 *  someone actually wants to know before committing to it. */
function clearsAt(minutes: number | null): string | null {
  if (minutes == null) return null
  const when = new Date(Date.now() + minutes * 60_000)
  const sameDay = when.toDateString() === new Date().toDateString()
  return when.toLocaleString(undefined, {
    weekday: sameDay ? undefined : 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function EditStatusModal({ onClose }: { onClose: () => void }) {
  const { user, refreshUser } = useAuth()
  const [emoji, setEmoji] = useState(user?.status?.emoji || '')
  const [text, setText] = useState(user?.status?.text || '')
  const [minutes, setMinutes] = useState<number | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const inputRef = useRef<HTMLInputElement>(null)
  const emojiWrapRef = useRef<HTMLDivElement>(null)
  const hasExistingStatus = !!user?.status

  // Escape closes the picker first, then the modal - closing both at once
  // loses the half-written status for the sake of one keystroke.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (pickerOpen) {
        setPickerOpen(false)
        e.stopPropagation()
      } else {
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pickerOpen, onClose])

  useEffect(() => {
    if (!pickerOpen) return
    const onClickAway = (e: MouseEvent) => {
      if (!emojiWrapRef.current?.contains(e.target as Node)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [pickerOpen])

  const applySuggestion = (s: (typeof SUGGESTIONS)[number]) => {
    setEmoji(s.emoji)
    setText(s.text)
    setMinutes(s.minutes)
    inputRef.current?.focus()
  }

  const handleSet = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim()) {
      setError('Say what you are doing, or pick one above.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await authApi.setStatus(text.trim(), emoji || null, minutes)
      await refreshUser()
      onClose()
    } catch (err) {
      setError(errorMessage(err, "Couldn't set status."))
      setBusy(false)
    }
  }

  const handleClear = async () => {
    setBusy(true)
    try {
      await authApi.clearStatus()
      await refreshUser()
      onClose()
    } catch (err) {
      setError(errorMessage(err, "Couldn't clear status."))
      setBusy(false)
    }
  }

  const expiry = clearsAt(minutes)

  // Portaled straight to <body> - Header has backdrop-filter (for its
  // frosted-glass look), which creates a CSS containing block for any
  // position:fixed descendant, so a modal rendered inside it would be
  // trapped inside the header's own small box instead of centering on the
  // full viewport.
  return createPortal(
    <AnimatePresence>
      <motion.div
        className="modal-overlay"
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        <motion.div
          className="modal-card status-modal"
          onClick={(e) => e.stopPropagation()}
          initial={{ opacity: 0, scale: 0.95, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 12 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          role="dialog"
          aria-modal="true"
          aria-label="Set your status"
        >
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
          <h3>Set your status</h3>

          <form className="status-form" onSubmit={handleSet}>
            {/* The field first, because it is what the suggestions fill in. */}
            <div className="status-field">
              <div className="status-emoji-wrap" ref={emojiWrapRef}>
                <button
                  type="button"
                  className={`status-emoji${emoji ? ' has-emoji' : ''}`}
                  onClick={() => setPickerOpen((open) => !open)}
                  aria-label={emoji ? `Status emoji: ${emoji}. Change it` : 'Pick an emoji'}
                  aria-expanded={pickerOpen}
                >
                  {emoji || <Icon name="clock" size={17} />}
                </button>

                {pickerOpen && (
                  <div className="status-emoji-picker" role="listbox" aria-label="Emoji">
                    {EMOJI_PRESETS.map((option) => (
                      <button
                        key={option}
                        type="button"
                        role="option"
                        aria-selected={emoji === option}
                        className={emoji === option ? 'is-chosen' : undefined}
                        onClick={() => {
                          setEmoji(option === emoji ? '' : option)
                          setPickerOpen(false)
                          inputRef.current?.focus()
                        }}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <input
                ref={inputRef}
                type="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="What's happening?"
                maxLength={80}
                autoFocus
                aria-label="Status message"
              />
              {text && (
                <button
                  type="button"
                  className="status-field-clear"
                  onClick={() => {
                    setText('')
                    setEmoji('')
                    inputRef.current?.focus()
                  }}
                  aria-label="Clear what you typed"
                >
                  <Icon name="close" size={13} />
                </button>
              )}
            </div>

            <div className="status-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.text}
                  type="button"
                  className={`status-chip${text === s.text && emoji === s.emoji ? ' is-chosen' : ''}`}
                  onClick={() => applySuggestion(s)}
                >
                  <span aria-hidden="true">{s.emoji}</span>
                  {s.text}
                </button>
              ))}
            </div>

            <label className="status-duration">
              <span>Clear after</span>
              <select
                value={minutes ?? ''}
                onChange={(e) => setMinutes(e.target.value ? Number(e.target.value) : null)}
              >
                {DURATIONS.map((d) => (
                  <option key={d.label} value={d.minutes ?? ''}>
                    {d.label}
                  </option>
                ))}
              </select>
              <small>{expiry ? `Clears at ${expiry}` : 'Stays until you change it'}</small>
            </label>

            {error && <p className="form-error">{error}</p>}

            <div className="modal-actions">
              {hasExistingStatus && (
                <button type="button" className="btn btn-danger-ghost" onClick={handleClear} disabled={busy}>
                  Clear status
                </button>
              )}
              <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
                {busy ? 'Saving...' : 'Set status'}
              </button>
            </div>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  )
}
