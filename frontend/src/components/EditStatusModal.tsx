import { useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useAuth } from '../context/AuthContext'
import { authApi, errorMessage } from '../services/api'
import Icon from './Icon'
import '../pages/DashboardPage.css'

const EMOJI_PRESETS = ['🌴', '🤒', '🏠', '🎯', '🚚', '📞', '☕']

const DURATIONS: { label: string; minutes: number | null }[] = [
  { label: "Don't clear", minutes: null },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '4 hours', minutes: 240 },
  { label: 'Today', minutes: 24 * 60 },
  { label: 'This week', minutes: 7 * 24 * 60 },
]

export default function EditStatusModal({ onClose }: { onClose: () => void }) {
  const { user, refreshUser } = useAuth()
  const [emoji, setEmoji] = useState(user?.status?.emoji || '')
  const [text, setText] = useState(user?.status?.text || '')
  const [minutes, setMinutes] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const hasExistingStatus = !!user?.status

  const handleSet = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim()) {
      setError('Enter a status message.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await authApi.setStatus(text.trim(), emoji || null, minutes)
      await refreshUser()
      onClose()
    } catch (err) {
      setError(errorMessage(err, 'Could not set status.'))
    } finally {
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
      setError(errorMessage(err, 'Could not clear status.'))
      setBusy(false)
    }
  }

  return (
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
          className="modal-card"
          onClick={(e) => e.stopPropagation()}
          initial={{ opacity: 0, scale: 0.95, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 12 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
        >
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
          <h3>Edit status</h3>
          <form className="form" onSubmit={handleSet}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {EMOJI_PRESETS.map((e) => (
                <button
                  key={e}
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setEmoji(e === emoji ? '' : e)}
                  style={emoji === e ? { borderColor: 'var(--accent)' } : undefined}
                  aria-label={`Use ${e}`}
                >
                  {e}
                </button>
              ))}
            </div>
            <label>
              <span>What's happening</span>
              <input
                type="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="On vacation, out sick, focusing..."
                maxLength={80}
                autoFocus
              />
            </label>
            <label>
              <span>Clear after</span>
              <select value={minutes ?? ''} onChange={(e) => setMinutes(e.target.value ? Number(e.target.value) : null)}>
                {DURATIONS.map((d) => (
                  <option key={d.label} value={d.minutes ?? ''}>
                    {d.label}
                  </option>
                ))}
              </select>
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
    </AnimatePresence>
  )
}
