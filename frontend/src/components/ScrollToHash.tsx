import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/** Scrolls to the element a URL's #hash names.
 *
 * The browser does this natively on a normal page load, but not in a SPA:
 * by the time React has rendered the target section, the browser has long
 * since given up looking for it. So "/#features" landed at the top of the
 * page and the Features link appeared to do nothing.
 *
 * The target may not exist for a while, and "a while" varies enormously.
 * A marketing section is there as soon as its chunk loads; the Gmail card
 * on /settings only exists once the settings request has come back, since
 * that page renders a spinner until then. This used to retry for thirty
 * animation frames - about half a second - which covers the first case and
 * nothing like the second, so "Reconnect it in Settings" quietly dropped
 * the reader at the top of the page.
 *
 * A MutationObserver waits for however long it actually takes instead of
 * guessing, and costs nothing while nothing is changing.
 *
 * Rendered once inside the router, so it covers every hash link in the app
 * rather than each one re-implementing the scroll itself. */
export default function ScrollToHash() {
  const { pathname, hash } = useLocation()

  useEffect(() => {
    if (!hash) return

    // A ceiling, so a hash naming something that will never exist - a typo,
    // a section that was removed - does not leave an observer running for
    // the life of the page.
    const GIVE_UP_AFTER_MS = 10_000

    let observer: MutationObserver | null = null
    let timeout = 0
    let highlight = 0

    const stop = () => {
      observer?.disconnect()
      observer = null
      window.clearTimeout(timeout)
    }

    const arrive = (target: Element) => {
      stop()

      const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      target.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })

      // Arriving somewhere in the middle of a long page is disorienting
      // unless something says "this is the thing you were sent to". The
      // class fades out on its own; the CSS lives with each target.
      target.classList.add('is-deep-linked')
      highlight = window.setTimeout(() => target.classList.remove('is-deep-linked'), 2400)

      // Scrolling moves the eye but not the keyboard. Without this, tabbing
      // after following the link resumes from the top of the document.
      if (target instanceof HTMLElement) {
        if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
        target.focus({ preventScroll: true })
      }
    }

    const find = () => {
      try {
        return document.querySelector(hash)
      } catch {
        // A hash that is not a valid selector - "#" alone, or something
        // with characters querySelector will not parse.
        return null
      }
    }

    const existing = find()
    if (existing) {
      arrive(existing)
    } else {
      observer = new MutationObserver(() => {
        const target = find()
        if (target) arrive(target)
      })
      observer.observe(document.body, { childList: true, subtree: true })
      timeout = window.setTimeout(stop, GIVE_UP_AFTER_MS)
    }

    return () => {
      stop()
      window.clearTimeout(highlight)
    }
  }, [pathname, hash])

  return null
}
