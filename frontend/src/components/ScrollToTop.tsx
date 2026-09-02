import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

// React Router doesn't reset scroll position on navigation - without this,
// going from a long page to a new one keeps the old scroll offset.
//
// Unless the URL says where to land. A #hash is an explicit instruction to
// go to one place on the new page, and this ran on every pathname change
// without checking for one - so ScrollToHash would find its target, scroll
// to it, and get yanked straight back to the top. That is why the
// dashboard's "Reconnect it in Settings" appeared to ignore its anchor.
export default function ScrollToTop() {
  const { pathname, hash } = useLocation()

  useEffect(() => {
    if (hash) return
    window.scrollTo(0, 0)
  }, [pathname, hash])

  return null
}
