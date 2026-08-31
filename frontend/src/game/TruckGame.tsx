import { useCallback, useEffect, useRef, useState } from 'react'
import Matter from 'matter-js'
import { generateRoute, SEGMENT_WIDTH, type Crate, type Route } from './route'
import { claimTicket, refillTickets, submitRun, flushQueue, type Ticket } from './scores'
import {
  createWorld, loadCrate, reloadCargo, recoverableCargo, planDrop, drive, brake,
  updateCargoState, currentPayout, DECK_MIN_OFFSET, DECK_MAX_OFFSET,
  type CargoBody, type TruckWorld,
} from './engine'
import './TruckGame.css'

/**
 * Haul a load from A to B without wrecking it.
 *
 * Loading is the first half of the game. You decide where every item goes on
 * the deck and which way up it sits - heavy low and central, the tall drum
 * laid down or braced by something beside it. Then you drive, and the only
 * thing holding the load on is how well you stacked it and how gently you
 * drive. Speed is not scored; what arrives intact is.
 *
 * Dropping something is a setback rather than a verdict: stop, back up, and
 * you can put it on again. The rig itself is what you cannot replace - it
 * takes damage from real impacts, and enough of them end the run outright.
 */

type Phase = 'loading' | 'driving' | 'reloading' | 'arrived' | 'failed' | 'wrecked'

const VIEW = { w: 900, h: 520 }

/** Keyboard nudge per press while aiming - fine enough to thread a gap. */
const AIM_STEP = 4

/** How long the wreck plays before the result takes over the screen. */
const WRECK_MS = 1100

const KIND_LABEL: Record<Crate['kind'], string> = {
  pallet: 'Pallet',
  crate: 'Crate',
  drum: 'Drum',
}

interface Props {
  /** Supplied by the server once the leaderboard exists; random until then. */
  seed?: number
  onFinish?: (result: { payout: number; delivered: number; lost: number }) => void
}

export default function TruckGame({ seed, onFinish }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const shellRef = useRef<HTMLDivElement>(null)
  const worldRef = useRef<TruckWorld | null>(null)
  const inputRef = useRef({ throttle: 0, braking: false })

  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [route, setRoute] = useState<Route>(() => generateRoute(seed ?? (Math.random() * 2 ** 31) | 0))
  const startedAt = useRef(0)
  const [phase, setPhase] = useState<Phase>('loading')
  const [placed, setPlaced] = useState(0)
  const [payout, setPayout] = useState(0)
  const [progress, setProgress] = useState(0)
  const [condition, setCondition] = useState(1)
  const [canRecover, setCanRecover] = useState(false)
  // Only the wreck has anything to watch before the result panel covers it.
  const [wreckPlayed, setWreckPlayed] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Aiming lives in a ref, not in state: it updates on every pointermove,
  // and re-rendering the whole component sixty times a second to move a
  // dashed rectangle would cost more than the physics does. The draw loop
  // reads it directly. `rotated` is mirrored into state only because a
  // button label depends on it.
  const aimRef = useRef({ offset: -30, rotated: false })
  const [rotated, setRotated] = useState(false)
  // Same reason: the draw loop needs the current index, and its effect
  // deliberately does not re-run on every placement.
  const placedRef = useRef(0)
  // The dropped item currently being put back on. The body lives in a ref
  // because only the physics touches it; its crate is mirrored into state
  // because the panel renders the item's weight and rate, and a ref read
  // during render would not re-render when it changed.
  const reloadRef = useRef<CargoBody | null>(null)
  const [reloadCrate, setReloadCrate] = useState<Crate | null>(null)
  // Written by the draw loop so pointer coordinates can be converted back
  // into world space with the exact camera that produced the frame.
  const cameraRef = useRef({ x: 0, y: 0, zoom: 1 })
  const wreckedAt = useRef(0)

  const aiming = phase === 'loading' || phase === 'reloading'

  // ---- world lifecycle ------------------------------------------------
  useEffect(() => {
    const world = createWorld(route)
    worldRef.current = world
    return () => {
      world.destroy()
      worldRef.current = null
    }
  }, [route])

  const startOver = useCallback(() => {
    // A ticket carries the seed, so taking one is what picks the route. With
    // none left (signed out, or offline having used the batch) the game still
    // plays on a local seed - it just cannot be submitted, which submitRun
    // handles by having nothing to send.
    const next = claimTicket()
    setTicket(next)
    setRoute(generateRoute(next ? next.seed : (Math.random() * 2 ** 31) | 0))
    setPhase('loading')
    setPlaced(0)
    placedRef.current = 0
    reloadRef.current = null
    setPayout(0)
    setProgress(0)
    setCondition(1)
    setCanRecover(false)
    setWreckPlayed(false)
    setReloadCrate(null)
    setRotated(false)
    aimRef.current = { offset: -30, rotated: false }
  }, [])

  // Top up tickets and push any runs finished offline, on load and whenever
  // the connection comes back.
  useEffect(() => {
    const sync = () => {
      void refillTickets().then(() => {
        setTicket((current) => current ?? claimTicket())
      })
      void flushQueue()
    }
    sync()
    window.addEventListener('online', sync)
    return () => window.removeEventListener('online', sync)
  }, [])

  // ---- aiming: point, turn, set down ------------------------------------

  /** The item the ghost is showing - the next off the dock while loading, or
   *  the one being picked up off the road. */
  const aimedCrate = useCallback((): Crate | null => {
    if (phase === 'reloading') return reloadRef.current?.crate ?? null
    if (phase === 'loading') return route.crates[placedRef.current] ?? null
    return null
  }, [phase, route])


  /** Keeps the item between the rear lip and the headboard. Aiming past the
   *  deck would place it somewhere the physics immediately rejects, which
   *  reads as the game ignoring the click. */
  const clampOffset = (offset: number, crate: Crate, laid: boolean) => {
    const halfW = (laid ? crate.h : crate.w) / 2
    return Math.max(DECK_MIN_OFFSET + halfW, Math.min(DECK_MAX_OFFSET - halfW, offset))
  }

  const aimAt = (clientX: number) => {
    const canvas = canvasRef.current
    const world = worldRef.current
    const crate = aimedCrate()
    if (!canvas || !world || !crate) return
    const rect = canvas.getBoundingClientRect()
    const cam = cameraRef.current
    const worldX = ((clientX - rect.left) * VIEW.w) / (rect.width * cam.zoom) + cam.x
    aimRef.current.offset = clampOffset(
      worldX - world.chassis.position.x, crate, aimRef.current.rotated,
    )
  }

  const turnAim = useCallback(() => {
    const crate = aimedCrate()
    if (!crate) return
    const laid = !aimRef.current.rotated
    aimRef.current.rotated = laid
    // Re-clamp: laying a long pallet down makes it narrower, and standing a
    // drum up makes it wider, either of which can push it off the deck.
    aimRef.current.offset = clampOffset(aimRef.current.offset, crate, laid)
    setRotated(laid)
  }, [aimedCrate])

  const placeHere = useCallback(() => {
    const world = worldRef.current
    if (!world) return

    // Recovering: the same body goes back on, keeping the damage it took.
    if (phase === 'reloading') {
      const target = reloadRef.current
      if (!target) return
      reloadCargo(world, target, aimRef.current.offset, aimRef.current.rotated)
      reloadRef.current = null
      setReloadCrate(null)
      aimRef.current.rotated = false
      setRotated(false)
      setPhase('driving')
      return
    }

    const crate = route.crates[placedRef.current]
    if (!crate) return
    loadCrate(world, crate, aimRef.current.offset, aimRef.current.rotated)
    placedRef.current += 1
    setPlaced(placedRef.current)
    // Each item starts upright again. Carrying the last turn over is a small
    // surprise every single time, and re-clamping for the new shape would
    // move the aim out from under the pointer as well.
    aimRef.current.rotated = false
    setRotated(false)
    const next = route.crates[placedRef.current]
    if (next) aimRef.current.offset = clampOffset(aimRef.current.offset, next, false)
  }, [route, phase])

  const depart = () => {
    if (placed === 0) return
    startedAt.current = performance.now()
    setPhase('driving')
  }

  /** Switches to placing the nearest dropped item back on the deck. */
  const startRecovery = useCallback(() => {
    const world = worldRef.current
    if (!world || phase !== 'driving') return
    const [nearest] = recoverableCargo(world).sort(
      (a, b) => Math.abs(a.body.position.x - world.chassis.position.x)
        - Math.abs(b.body.position.x - world.chassis.position.x),
    )
    if (!nearest) return
    inputRef.current.throttle = 0
    inputRef.current.braking = false
    reloadRef.current = nearest
    setReloadCrate(nearest.crate)
    aimRef.current = { offset: -30, rotated: false }
    setRotated(false)
    setPhase('reloading')
  }, [phase])

  // ---- render + step loop ---------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const css = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
    const COLORS = {
      sky: token('--bg', '#161616'),
      ground: token('--border', '#322f2a'),
      ink: token('--text', '#f5f4f0'),
      muted: token('--hint', '#9b988f'),
      accent: token('--accent', '#c3f832'),
      amber: token('--amber', '#e0b854'),
      danger: token('--red', '#ff5c52'),
    }

    let raf = 0
    let last = performance.now()

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      canvas.width = Math.round(rect.width * dpr)
      canvas.height = Math.round(rect.height * dpr)
    }
    resize()
    window.addEventListener('resize', resize)

    // Cargo is drawn as what it actually is rather than as identical boxes.
    // The shape is the whole basis of the loading decision, so the player has
    // to be able to read it at a glance: a drum stood on end looks precarious
    // because it is.
    const drawCargo = (entry: CargoBody) => {
      const { body, w, h } = entry
      const fill = entry.damage > 0.6 ? COLORS.danger : entry.damage > 0.2 ? COLORS.amber : COLORS.muted
      ctx.save()
      ctx.translate(body.position.x, body.position.y)
      ctx.rotate(body.angle)
      ctx.fillStyle = fill

      if (entry.crate.kind === 'drum') {
        const r = Math.min(w, h) * 0.32
        ctx.beginPath()
        if (ctx.roundRect) ctx.roundRect(-w / 2, -h / 2, w, h, r)
        else ctx.rect(-w / 2, -h / 2, w, h)
        ctx.fill()
        // Hoops, drawn across the drum's own short axis whichever way it is
        // lying, so a laid-down drum still reads as a drum.
        ctx.strokeStyle = COLORS.sky
        ctx.lineWidth = 2
        for (const t of [-0.2, 0.2]) {
          ctx.beginPath()
          if (h >= w) {
            ctx.moveTo(-w / 2, h * t)
            ctx.lineTo(w / 2, h * t)
          } else {
            ctx.moveTo(w * t, -h / 2)
            ctx.lineTo(w * t, h / 2)
          }
          ctx.stroke()
        }
      } else {
        ctx.fillRect(-w / 2, -h / 2, w, h)
        ctx.strokeStyle = COLORS.sky
        ctx.lineWidth = 2
        ctx.beginPath()
        if (entry.crate.kind === 'pallet') {
          // Fork pockets along the underside.
          ctx.moveTo(-w / 2, h / 2 - 3)
          ctx.lineTo(w / 2, h / 2 - 3)
        } else {
          ctx.moveTo(-w / 2, -h / 2)
          ctx.lineTo(w / 2, h / 2)
        }
        ctx.stroke()
      }

      if (entry.crate.fragile) {
        ctx.strokeStyle = COLORS.amber
        ctx.lineWidth = 2
        ctx.strokeRect(-w / 2 + 1.5, -h / 2 + 1.5, w - 3, h - 3)
      }
      ctx.restore()
    }

    /** A short burst where the rig was. Deliberately spare - a ring, some
     *  shards and nothing else. A cartoon fireball would be at odds with
     *  every other thing on this site. */
    const drawWreck = (world: TruckWorld, t: number) => {
      const { x, y } = world.chassis.position
      const fade = 1 - t
      ctx.save()
      ctx.globalAlpha = fade
      ctx.strokeStyle = COLORS.amber
      ctx.lineWidth = 3 * fade + 1
      ctx.beginPath()
      ctx.arc(x, y, 30 + t * 190, 0, Math.PI * 2)
      ctx.stroke()

      ctx.strokeStyle = COLORS.danger
      ctx.lineWidth = 3
      for (let i = 0; i < 14; i++) {
        const angle = (i / 14) * Math.PI * 2 + 0.4
        // Spread the shards over different speeds, or it reads as a single
        // expanding wheel of spokes rather than debris.
        const speed = 90 + ((i * 37) % 110)
        const near = 14 + t * speed
        const far = near + 16 + (1 - t) * 12
        ctx.beginPath()
        ctx.moveTo(x + Math.cos(angle) * near, y + Math.sin(angle) * near - t * 24)
        ctx.lineTo(x + Math.cos(angle) * far, y + Math.sin(angle) * far - t * 24)
        ctx.stroke()
      }
      ctx.restore()
    }

    let lastCanRecover = false

    const frame = (now: number) => {
      const world = worldRef.current
      if (!world) {
        raf = requestAnimationFrame(frame)
        return
      }

      // Fixed timestep. A variable one makes a physics sim behave
      // differently on a 144Hz screen than a 60Hz one, which for a game
      // scored on outcome would mean the monitor decides the score.
      const elapsed = Math.min(now - last, 60)
      last = now
      if (phase === 'driving' || phase === 'loading' || phase === 'reloading') {
        const steps = Math.max(1, Math.round(elapsed / (1000 / 60)))
        for (let i = 0; i < steps; i++) {
          if (phase === 'driving') {
            drive(world, inputRef.current.throttle)
            if (inputRef.current.braking) brake(world)
          }
          Matter.Engine.update(world.engine, 1000 / 60)
        }
        updateCargoState(world)
      }

      // ---- draw ----
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      const scale = (rect.width * dpr) / VIEW.w
      ctx.setTransform(scale, 0, 0, scale, 0, 0)
      ctx.fillStyle = COLORS.sky
      ctx.fillRect(0, 0, VIEW.w, VIEW.h)

      // Camera trails the truck, keeping it left-of-centre so the road ahead
      // is what the player is actually looking at. Aiming pulls in close
      // instead: the deck is what is being looked at, and placing an item to
      // the pixel is impossible when the whole deck is 174px wide on screen.
      const closeUp = phase === 'loading' || phase === 'reloading'
      const zoom = closeUp ? 2 : 1
      const camX = closeUp
        ? world.chassis.position.x - VIEW.w / (2 * zoom)
        : Math.max(0, world.chassis.position.x - VIEW.w * 0.35)
      const camY = closeUp
        ? world.chassis.position.y - (VIEW.h * 0.62) / zoom
        : Math.max(0, world.chassis.position.y - VIEW.h * 0.55)
      cameraRef.current = { x: camX, y: camY, zoom }
      ctx.save()
      if (zoom !== 1) ctx.scale(zoom, zoom)
      ctx.translate(-camX, -camY)

      // Terrain
      const floor = camY + VIEW.h / zoom + 400
      ctx.fillStyle = COLORS.ground
      ctx.beginPath()
      ctx.moveTo(0, floor)
      for (let i = 0; i < route.heights.length; i++) {
        ctx.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }
      ctx.lineTo((route.heights.length - 1) * SEGMENT_WIDTH, floor)
      ctx.closePath()
      ctx.fill()

      // Finish marker
      ctx.strokeStyle = COLORS.accent
      ctx.lineWidth = 3
      ctx.setLineDash([10, 8])
      ctx.beginPath()
      ctx.moveTo(world.finishX, 0)
      ctx.lineTo(world.finishX, floor)
      ctx.stroke()
      ctx.setLineDash([])

      // Truck, coloured by how much of a beating it has taken - the number in
      // the HUD is the precise version, this is the one you see without
      // looking away from the road.
      const bodyColor = phase === 'wrecked' || world.truckDamage > 0.75
        ? COLORS.danger
        : world.truckDamage > 0.4 ? COLORS.amber : COLORS.accent
      const drawBody = (body: Matter.Body, fill: string) => {
        ctx.fillStyle = fill
        ctx.beginPath()
        const verts = body.vertices
        ctx.moveTo(verts[0].x, verts[0].y)
        for (let i = 1; i < verts.length; i++) ctx.lineTo(verts[i].x, verts[i].y)
        ctx.closePath()
        ctx.fill()
      }
      for (const part of world.chassis.parts.slice(1)) {
        // The wheels are parts of the same rigid body now, so they would
        // otherwise be drawn twice - once as a 25-sided polygon in the body
        // colour, once as the circle below.
        if (part.label !== 'wheel') drawBody(part, bodyColor)
      }
      for (const wheel of [world.rearWheel, world.frontWheel]) {
        const r = wheel.circleRadius || 20
        ctx.fillStyle = COLORS.ink
        ctx.beginPath()
        ctx.arc(wheel.position.x, wheel.position.y, r, 0, Math.PI * 2)
        ctx.fill()
        // A spoke, turned by how far the rig has travelled. The wheels no
        // longer rotate as bodies of their own, and a wheel that visibly
        // does not turn makes the whole truck read as sliding rather than
        // driving - which is exactly what it is doing, and the one part of
        // that the player should not have to notice.
        ctx.strokeStyle = COLORS.muted
        ctx.lineWidth = 3
        ctx.save()
        ctx.translate(wheel.position.x, wheel.position.y)
        ctx.rotate(world.chassis.position.x / r + world.chassis.angle)
        ctx.beginPath()
        ctx.moveTo(-r * 0.6, 0)
        ctx.lineTo(r * 0.6, 0)
        ctx.stroke()
        ctx.restore()
      }

      const withinReach = phase === 'driving' ? recoverableCargo(world) : []
      for (const entry of world.cargo) {
        if (entry.state === 'gone') continue
        drawCargo(entry)
        // Ring anything lying on the road, brightly if it is close enough to
        // collect - so going back for it is an offer rather than a guess.
        if (entry.state === 'road' && phase === 'driving') {
          const reachable = withinReach.includes(entry)
          ctx.save()
          ctx.strokeStyle = reachable ? COLORS.accent : COLORS.muted
          ctx.globalAlpha = reachable ? 0.9 : 0.35
          ctx.lineWidth = 2
          ctx.setLineDash([4, 4])
          ctx.strokeRect(
            entry.body.position.x - entry.w / 2 - 6,
            entry.body.position.y - entry.h / 2 - 6,
            entry.w + 12, entry.h + 12,
          )
          ctx.restore()
        }
      }

      // The ghost: exactly the rectangle placeHere would create, in exactly
      // the spot, worked out by the same function the physics uses.
      const pending = phase === 'reloading'
        ? reloadRef.current?.crate ?? null
        : route.crates[placedRef.current] ?? null
      if (closeUp && pending) {
        const spot = planDrop(world, pending, aimRef.current.offset, aimRef.current.rotated)
        ctx.save()
        ctx.strokeStyle = COLORS.accent
        ctx.lineWidth = 1.5
        ctx.setLineDash([5, 4])
        ctx.strokeRect(spot.x - spot.w / 2, spot.y - spot.h / 2, spot.w, spot.h)
        // A drop line down to the deck, so it reads as an item being set
        // down in that column rather than one floating in mid-air.
        ctx.globalAlpha = 0.45
        ctx.beginPath()
        ctx.moveTo(spot.x, spot.y + spot.h / 2)
        ctx.lineTo(spot.x, world.bedTop())
        ctx.stroke()
        ctx.restore()
      }

      if (phase === 'wrecked') {
        drawWreck(world, Math.min(1, (now - wreckedAt.current) / WRECK_MS))
      }

      ctx.restore()

      if (phase === 'driving') {
        setCondition(1 - world.truckDamage)
        const offer = withinReach.length > 0
        if (offer !== lastCanRecover) {
          lastCanRecover = offer
          setCanRecover(offer)
        }

        setProgress(Math.min(1, world.chassis.position.x / world.finishX))
        setPayout(currentPayout(world))

        const submit = (result: { payout: number; delivered: number; lost: number }) => {
          onFinish?.(result)
          if (ticket) {
            void submitRun({
              token: ticket.token,
              ...result,
              duration_ms: Math.round(performance.now() - startedAt.current),
            })
          }
        }

        if (world.truckDamage >= 1) {
          wreckedAt.current = now
          setPhase('wrecked')
          setPayout(0)
          // Still submitted. A wreck is a real result, and a board that only
          // ever heard about the good runs would quietly reward quitting out
          // of the bad ones.
          submit({ payout: 0, delivered: 0, lost: world.cargo.length })
        } else {
          const reached = world.chassis.position.x >= world.finishX
          // Only a load that is beyond recovery ends the run early. Items
          // lying on the road do not, because going back for them is now a
          // legitimate move.
          const nothingLeft = world.cargo.every((c) => c.state === 'gone')
          if (reached || nothingLeft) {
            const final = reached ? currentPayout(world) : 0
            setPhase(reached ? 'arrived' : 'failed')
            setPayout(final)
            submit({
              payout: final,
              delivered: world.cargo.filter((c) => c.state === 'deck' && c.damage < 0.999).length,
              lost: world.cargo.filter((c) => c.state !== 'deck').length,
            })
          }
        }
      }

      raf = requestAnimationFrame(frame)
    }

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [route, phase, onFinish, ticket])

  // The wreck plays out before the result panel covers it up. Every other
  // ending has nothing to watch, so its panel is derived rather than timed.
  useEffect(() => {
    if (phase !== 'wrecked') return
    const timer = setTimeout(() => setWreckPlayed(true), WRECK_MS)
    return () => clearTimeout(timer)
  }, [phase])

  // ---- keyboard --------------------------------------------------------
  // The same keys mean different things in the two modes, which is why this
  // branches on phase rather than mapping keys straight to the throttle:
  // left and right aim while placing and drive while driving.
  useEffect(() => {
    const LEFT = ['ArrowLeft', 'KeyA']
    const RIGHT = ['ArrowRight', 'KeyD']

    const down = (e: KeyboardEvent) => {
      if (phase === 'loading' || phase === 'reloading') {
        const crate = phase === 'reloading'
          ? reloadRef.current?.crate
          : route.crates[placedRef.current]
        if (!crate) return
        if (LEFT.includes(e.code) || RIGHT.includes(e.code)) {
          e.preventDefault()
          const dir = RIGHT.includes(e.code) ? 1 : -1
          aimRef.current.offset = clampOffset(
            aimRef.current.offset + dir * AIM_STEP, crate, aimRef.current.rotated,
          )
        }
        if (e.code === 'KeyR') turnAim()
        if (e.code === 'Enter' || e.code === 'Space') {
          e.preventDefault()
          placeHere()
        }
        return
      }
      if (phase !== 'driving') return
      if (RIGHT.includes(e.code)) inputRef.current.throttle = 1
      if (LEFT.includes(e.code)) inputRef.current.throttle = -1
      if (e.code === 'KeyE') startRecovery()
      if (e.code === 'Space') {
        e.preventDefault()
        inputRef.current.braking = true
      }
    }
    const up = (e: KeyboardEvent) => {
      if ([...LEFT, ...RIGHT].includes(e.code)) inputRef.current.throttle = 0
      if (e.code === 'Space') inputRef.current.braking = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [phase, route, turnAim, placeHere, startRecovery])

  // ---- fullscreen ------------------------------------------------------
  const toggleFullscreen = async () => {
    const shell = shellRef.current
    if (!shell) return
    if (document.fullscreenElement) {
      await document.exitFullscreen()
      return
    }
    await shell.requestFullscreen()
    // Keyboard Lock is the ONLY way a page can hold on to Ctrl+W and friends,
    // and the spec only allows it inside JS-initiated fullscreen. Chrome and
    // Edge implement it; Firefox and Safari do not, so this is a genuine
    // best-effort - there is no fallback that works.
    const kb = (navigator as Navigator & {
      keyboard?: { lock: (keys?: string[]) => Promise<void> }
    }).keyboard
    try {
      await kb?.lock(['KeyW', 'KeyT', 'KeyN', 'Escape'])
    } catch {
      // Locking is a nicety; losing it must not stop the game going fullscreen.
    }
  }

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const remaining = route.crates.length - placed
  const nextCrate = route.crates[placed]
  const shownCrate = phase === 'reloading' ? reloadCrate : nextCrate
  const conditionPct = Math.max(0, Math.round(condition * 100))

  return (
    <div className="tg" ref={shellRef}>
      <div className="tg-hud">
        <span className="tg-stat">Loaded <b>{placed}/{route.crates.length}</b></span>
        <span className="tg-stat">On board <b>${payout.toLocaleString('en-US')}</b></span>
        <span className="tg-stat is-muted">Full load <b>${route.maxPayout.toLocaleString('en-US')}</b></span>
        <span className={`tg-stat${conditionPct <= 35 ? ' is-critical' : conditionPct <= 70 ? ' is-warn' : ''}`}>
          Rig <b>{conditionPct}%</b>
        </span>
        <button type="button" className="tg-icon-btn" onClick={toggleFullscreen}>
          {isFullscreen ? 'Exit full screen' : 'Full screen'}
        </button>
      </div>

      <div className="tg-stage">
        <canvas
          ref={canvasRef}
          className={`tg-canvas${aiming ? ' is-aiming' : ''}`}
          // Pointer events rather than mouse and touch pairs: one code path
          // covers a mouse, a finger and a stylus, and a tap on a phone
          // arrives as a down/up at the same spot, which places there.
          onPointerMove={aiming ? (e) => aimAt(e.clientX) : undefined}
          onPointerDown={aiming ? (e) => {
            e.currentTarget.setPointerCapture(e.pointerId)
            aimAt(e.clientX)
          } : undefined}
          onPointerUp={aiming ? (e) => {
            aimAt(e.clientX)
            placeHere()
          } : undefined}
        />

        {phase === 'driving' && (
          <div className="tg-progress" aria-hidden="true">
            <span style={{ width: `${progress * 100}%` }} />
          </div>
        )}

        {phase === 'driving' && canRecover && (
          <div className="tg-recover">
            <button type="button" className="btn btn-primary btn-sm" onClick={startRecovery}>
              Load it back on
            </button>
            <span className="tg-recover-key">or press E</span>
          </div>
        )}

        {aiming && (
          // Pointer events are off on the overlay itself so the deck stays
          // clickable underneath it; only the panel takes them back.
          <div className="tg-overlay tg-overlay-loading">
            <div className="tg-panel">
              {shownCrate ? (
                <>
                  <p className="tg-panel-line">
                    <b>{KIND_LABEL[shownCrate.kind]}</b> · {shownCrate.weight}kg
                    {shownCrate.fragile ? ' · fragile' : ''} · pays $
                    {shownCrate.rate.toLocaleString('en-US')}
                    {phase === 'loading' && (
                      <span className="tg-panel-rest"> · {remaining} still on the dock</span>
                    )}
                  </p>
                  <p className="tg-panel-hint">
                    {phase === 'reloading'
                      ? 'Find it a spot on the deck. It keeps whatever the fall did to it.'
                      : 'Point at the deck and click to set it down. Heavy and low rides best.'}
                  </p>
                </>
              ) : (
                <p className="tg-panel-line">
                  <b>Trailer loaded.</b>
                  <span className="tg-panel-rest"> Nothing is strapped down - drive gently.</span>
                </p>
              )}
              <div className="tg-panel-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={turnAim}
                  disabled={!shownCrate}
                >
                  {rotated ? 'Stand it upright' : 'Lay it on its side'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={placeHere}
                  disabled={!shownCrate}
                >
                  Set down
                </button>
                {phase === 'loading' && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={depart}
                    disabled={placed === 0}
                  >
                    {remaining > 0 ? `Depart with ${placed}` : 'Depart'}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {(phase === 'arrived' || phase === 'failed' || (phase === 'wrecked' && wreckPlayed)) && (
          <div className="tg-overlay">
            <p className="tg-overlay-title">
              {phase === 'arrived' ? 'Delivered' : phase === 'wrecked' ? 'Rig totalled' : 'Load lost'}
            </p>
            <p className="tg-overlay-text">
              {phase === 'arrived'
                ? `$${payout.toLocaleString('en-US')} of $${route.maxPayout.toLocaleString('en-US')} arrived intact.`
                : phase === 'wrecked'
                  ? 'One impact too many. The load never got there, and neither did the truck.'
                  : 'Everything came off the trailer before the drop.'}
            </p>
            <button type="button" className="btn btn-primary" onClick={startOver}>
              New route
            </button>
          </div>
        )}
      </div>

      {/* Held buttons, so touch devices get the same continuous throttle a
          held key gives - a tap-per-press control would make the hills
          unplayable on a phone. Hidden while placing, where they mean
          nothing and only crowd the panel. */}
      {!aiming && (
        <div className="tg-controls">
          <button
            type="button"
            className="tg-pedal"
            onPointerDown={() => { inputRef.current.throttle = -1 }}
            onPointerUp={() => { inputRef.current.throttle = 0 }}
            onPointerLeave={() => { inputRef.current.throttle = 0 }}
            aria-label="Reverse"
          >
            ◀
          </button>
          <button
            type="button"
            className="tg-pedal is-brake"
            onPointerDown={() => { inputRef.current.braking = true }}
            onPointerUp={() => { inputRef.current.braking = false }}
            onPointerLeave={() => { inputRef.current.braking = false }}
            aria-label="Brake"
          >
            Brake
          </button>
          <button
            type="button"
            className="tg-pedal"
            onPointerDown={() => { inputRef.current.throttle = 1 }}
            onPointerUp={() => { inputRef.current.throttle = 0 }}
            onPointerLeave={() => { inputRef.current.throttle = 0 }}
            aria-label="Forward"
          >
            ▶
          </button>
        </div>
      )}
      <p className="tg-hint">
        {aiming
          ? 'Click the deck to set the item down · arrows to nudge · R to turn it · Enter to place'
          : 'Arrows or A/D to drive · Space to brake · back up to anything you drop and press E'}
      </p>
    </div>
  )
}
