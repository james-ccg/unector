import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dashboardApi, errorMessage, type AppNotification } from '../services/api'
import './NotificationBell.css'

/**
 * The bell in the header, and the list behind it.
 *
 * This is the channel that always arrives: an email address can be wrong
 * and Telegram refuses to let a bot message anyone who has not started a
 * chat with it, so whatever the other two dropped can still be found here.
 * That also makes it the one channel with nothing to configure.
 *
 * It polls rather than holding a socket open. Dispatch news is minutes-
 * fresh, not seconds-fresh, and a socket per signed-in tab is a lot of
 * machinery for a number that changes a few times a day. Polling stops
 * while the tab is hidden, so a dashboard left open overnight is not still
 * asking every minute at 3am.
 */

const POLL_INTERVAL_MS = 60_000

function ago(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export default function NotificationBell() {
  const [items, setItems] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    try {
      const data = await dashboardApi.listNotifications({ limit: 20 })
      setItems(data.notifications)
      setUnread(data.unread)
      setError('')
    } catch (err) {
      // A failed poll is not worth a banner - the next one probably works,
      // and the panel says so if it is opened meanwhile.
      setError(errorMessage(err, "Couldn't load your notifications."))
    }
  }, [])

  useEffect(() => {
    // Queued rather than called straight from the effect body: the lint rule
    // reads a bare call as a synchronous setState and cascading renders,
    // which an async fetch is not - but the same deferral is what the rest
    // of the app uses, so this stays consistent instead of silenced.
    queueMicrotask(load)
    let timer: number | undefined

    const start = () => {
      window.clearInterval(timer)
      timer = window.setInterval(load, POLL_INTERVAL_MS)
    }
    const onVisibility = () => {
      if (document.hidden) {
        window.clearInterval(timer)
      } else {
        load()
        start()
      }
    }

    start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [load])

  // Close on an outside click or Escape, the way the profile menu does.
  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const markAllRead = async () => {
    try {
      const result = await dashboardApi.markNotificationsRead()
      setUnread(result.unread)
      setItems((prev) => prev.map((item) => ({ ...item, read: true })))
    } catch (err) {
      setError(errorMessage(err, "Couldn't mark those read."))
    }
  }

  const openItem = async (item: AppNotification) => {
    if (!item.read) {
      try {
        const result = await dashboardApi.markNotificationsRead([item.id])
        setUnread(result.unread)
        setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, read: true } : n)))
      } catch {
        // Reading it matters more than recording that it was read.
      }
    }
    if (item.link) {
      setOpen(false)
      navigate(item.link)
    }
  }

  return (
    <div className="nb-wrap" ref={panelRef}>
      <button
        type="button"
        className="nb-button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
      >
        <Bell size={18} />
        {unread > 0 && <span className="nb-badge">{unread > 9 ? '9+' : unread}</span>}
      </button>

      {open && (
        <div className="nb-panel" role="dialog" aria-label="Notifications">
          <div className="nb-head">
            <span className="nb-title">Notifications</span>
            {unread > 0 && (
              <button type="button" className="nb-mark" onClick={markAllRead}>
                Mark all read
              </button>
            )}
          </div>

          {error && <p className="nb-error">{error}</p>}

          {items.length === 0 && !error ? (
            <p className="nb-empty">Nothing yet. Dispatch news and account notices land here.</p>
          ) : (
            <ul className="nb-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={item.read ? 'nb-item' : 'nb-item is-unread'}
                    onClick={() => openItem(item)}
                  >
                    <span className="nb-item-title">{item.title}</span>
                    {item.body && <span className="nb-item-body">{item.body}</span>}
                    <span className="nb-item-time">{ago(item.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
