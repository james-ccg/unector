import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/** Scrolls to the element a URL's #hash names.
 *
 * The browser does this natively on a normal page load, but not in a SPA:
 * by the time React has rendered the target section, the browser has long
 * since given up looking for it. So "/#features" landed at the top of the
 * page and the Features link appeared to do nothing.
 *
 * Rendered once inside the router, so it covers every hash link in the app
 * rather than each one re-implementing the scroll itself. */
export default function ScrollToHash() {
  const { pathname, hash } = useLocation()

  useEffect(() => {
    if (!hash) {
      return
    }

    // Lazily-loaded routes mount a frame or two after the location changes,
    // so the element usually isn't there on the first look - retry briefly
    // instead of scrolling to nothing.
    let frames = 0
    let raf = 0

    const tryScroll = () => {
      const target = document.querySelector(hash)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
      if (frames++ < 30) {
        raf = requestAnimationFrame(tryScroll)
      }
    }

    raf = requestAnimationFrame(tryScroll)
    return () => cancelAnimationFrame(raf)
  }, [pathname, hash])

  return null
}
