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

    let clear = 0

    const tryScroll = () => {
      const target = document.querySelector(hash)
      if (!target) {
        if (frames++ < 30) raf = requestAnimationFrame(tryScroll)
        return
      }

      const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      target.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })

      // Arriving somewhere in the middle of a long page is disorienting
      // unless something says "this is the thing you were sent to". The
      // class fades out on its own; the CSS lives with each target.
      target.classList.add('is-deep-linked')
      clear = window.setTimeout(() => target.classList.remove('is-deep-linked'), 2400)

      // Scrolling moves the eye but not the keyboard. Without this, tabbing
      // after following the link resumes from the top of the document.
      if (target instanceof HTMLElement) {
        if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
        target.focus({ preventScroll: true })
      }
    }

    raf = requestAnimationFrame(tryScroll)
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(clear)
    }
  }, [pathname, hash])

  return null
}
