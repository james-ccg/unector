import { useCallback, useEffect, useRef, useState } from 'react'
import Matter from 'matter-js'
import { generateRoute, SEGMENT_WIDTH, BASE_GROUND_Y as BASE, type Crate, type Route } from './route'
import { claimTicket, refillTickets, submitRun, flushQueue, type Ticket } from './scores'
import {
  createWorld, loadCrate, reloadCargo, recoverableCargo, explodeTruck, planDrop,
  drive, brake, coast, updateCargoState, currentPayout, DECK_MIN_OFFSET, DECK_MAX_OFFSET,
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

/** How long the wreck plays before the result takes over the screen. The
 *  debris is real physics, so this is long enough for it to land. */
const WRECK_MS = 2400

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

  /** Turns a pointer position into world coordinates, using the exact
   *  camera the last frame was drawn with. */
  const pointerToWorld = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const cam = cameraRef.current
    return {
      x: ((clientX - rect.left) * VIEW.w) / (rect.width * cam.zoom) + cam.x,
      y: ((clientY - rect.top) * VIEW.h) / (rect.height * cam.zoom) + cam.y,
    }
  }

  /** Switches to placing a dropped item back on the deck. With no item
   *  given, takes the nearest one within reach. */
  const startRecovery = useCallback((pick?: CargoBody) => {
    const world = worldRef.current
    if (!world || phase !== 'driving') return
    const reachable = recoverableCargo(world)
    const nearest = pick && reachable.includes(pick)
      ? pick
      : reachable.sort(
        (a, b) => Math.abs(a.body.position.x - world.chassis.position.x)
          - Math.abs(b.body.position.x - world.chassis.position.x),
      )[0]
    if (!nearest) return
    inputRef.current.throttle = 0
    inputRef.current.braking = false
    reloadRef.current = nearest
    setReloadCrate(nearest.crate)
    aimRef.current = { offset: -30, rotated: false }
    setRotated(false)
    setPhase('reloading')
  }, [phase])

  /** Picking a dropped item up by pointing at it - a click on a desktop, a
   *  tap on a phone. The keyboard shortcut stays for people already driving
   *  with their hands on the keys. */
  const pickUpAt = (clientX: number, clientY: number) => {
    const world = worldRef.current
    if (!world) return
    const at = pointerToWorld(clientX, clientY)
    if (!at) return
    // Generous hit box: these are small objects, a finger is not, and the
    // only thing a miss can do is nothing.
    const hit = recoverableCargo(world).find((entry) => (
      Math.abs(entry.body.position.x - at.x) < entry.w / 2 + 18
      && Math.abs(entry.body.position.y - at.y) < entry.h / 2 + 18
    ))
    if (hit) startRecovery(hit)
  }

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

    // Ground texture, built once. A flat fill reads as a silhouette rather
    // than as earth, and at this scale a scatter of specks does more than
    // any amount of shading. It is painted inside the world transform, so
    // it scrolls with the ground instead of sitting still behind it.
    const grain = (() => {
      const tile = document.createElement('canvas')
      tile.width = 18
      tile.height = 18
      const tc = tile.getContext('2d')
      if (!tc) return COLORS.ground
      tc.fillStyle = COLORS.ground
      tc.fillRect(0, 0, 18, 18)
      tc.fillStyle = 'rgba(255,255,255,0.05)'
      for (const [x, y, r] of [[3, 5, 1.1], [12, 2, 1.5], [8, 10, 1], [15, 14, 1.2], [2, 15, 0.9]]) {
        tc.beginPath()
        tc.arc(x, y, r, 0, Math.PI * 2)
        tc.fill()
      }
      tc.fillStyle = 'rgba(0,0,0,0.10)'
      tc.fillRect(0, 8, 18, 1)
      tc.fillRect(9, 0, 1, 18)
      return ctx.createPattern(tile, 'repeat') ?? COLORS.ground
    })()

    // Where the tyres have scrubbed. Kept in world coordinates and capped,
    // so a long run cannot grow the list without bound.
    const skids: { x: number; y: number }[] = []

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
    /**
     * Materials, not theme colours.
     *
     * These are objects in a scene rather than parts of the interface, and
     * they were all drawn in one muted grey, which made a stack read as a
     * row of identical slabs - when telling a heavy timber pallet from a
     * steel drum at a glance is the entire loading decision. Fixed tones
     * work in both themes because the ground behind them is textured and
     * mid-dark either way.
     */
    const MATERIAL: Record<Crate['kind'], { base: string; light: string; dark: string }> = {
      pallet: { base: '#8a6a43', light: 'rgba(255,236,205,0.16)', dark: 'rgba(40,26,12,0.4)' },
      crate: { base: '#a5804f', light: 'rgba(255,240,214,0.18)', dark: 'rgba(48,32,14,0.4)' },
      drum: { base: '#6f7b86', light: 'rgba(226,240,255,0.2)', dark: 'rgba(16,24,32,0.45)' },
    }

    const drawCargo = (entry: CargoBody) => {
      const { body, w, h } = entry
      const skin = MATERIAL[entry.crate.kind]
      ctx.save()
      ctx.translate(body.position.x, body.position.y)
      ctx.rotate(body.angle)
      ctx.fillStyle = skin.base

      if (entry.crate.kind === 'drum') {
        const r = Math.min(w, h) * 0.3
        const barrel = new Path2D()
        barrel.roundRect(-w / 2, -h / 2, w, h, r)
        ctx.fill(barrel)
        // Rolled steel: a bright line down one side and shade on the other.
        ctx.save()
        ctx.clip(barrel)
        const sheen = h >= w
          ? ctx.createLinearGradient(-w / 2, 0, w / 2, 0)
          : ctx.createLinearGradient(0, -h / 2, 0, h / 2)
        sheen.addColorStop(0, skin.dark)
        sheen.addColorStop(0.32, skin.light)
        sheen.addColorStop(1, skin.dark)
        ctx.fillStyle = sheen
        ctx.fill(barrel)
        ctx.restore()
        // Rolling hoops, across the drum's short axis whichever way it lies.
        ctx.strokeStyle = 'rgba(0,0,0,0.45)'
        ctx.lineWidth = 2.5
        for (const t of [-0.26, 0.26]) {
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
        // Boards. Timber reads as timber the moment the planks are visible;
        // a plain rectangle reads as a brick.
        ctx.strokeStyle = skin.dark
        ctx.lineWidth = 1
        const boards = Math.max(2, Math.round(h / 9))
        for (let i = 1; i < boards; i++) {
          const y = -h / 2 + (h * i) / boards
          ctx.beginPath()
          ctx.moveTo(-w / 2, y)
          ctx.lineTo(w / 2, y)
          ctx.stroke()
        }
        if (entry.crate.kind === 'pallet') {
          // The pallet itself: a darker base with feet under the load.
          ctx.fillStyle = 'rgba(0,0,0,0.35)'
          ctx.fillRect(-w / 2, h / 2 - 6, w, 6)
          ctx.fillStyle = skin.base
          for (const t of [-0.42, 0, 0.42]) {
            ctx.fillRect(w * t - 4, h / 2 - 5, 8, 4)
          }
        } else {
          // Corner bracing, the way a shipping crate is actually built.
          ctx.strokeStyle = skin.dark
          ctx.lineWidth = 2
          ctx.strokeRect(-w / 2 + 2, -h / 2 + 2, w - 4, h - 4)
          ctx.beginPath()
          ctx.moveTo(-w / 2 + 2, -h / 2 + 2)
          ctx.lineTo(w / 2 - 2, h / 2 - 2)
          ctx.stroke()
        }
      }

      // A lit top edge, so a stack has depth instead of reading as a row of
      // flat cut-outs.
      ctx.fillStyle = skin.light
      ctx.fillRect(-w / 2, -h / 2, w, 2.5)

      // Damage as a wash over the material rather than a replacement colour,
      // so a battered crate is still recognisably a crate.
      if (entry.damage > 0.02) {
        ctx.fillStyle = entry.damage > 0.55
          ? `rgba(214,64,52,${0.25 + entry.damage * 0.5})`
          : `rgba(214,150,52,${entry.damage * 0.6})`
        ctx.fillRect(-w / 2, -h / 2, w, h)
      }

      if (entry.crate.fragile) {
        ctx.strokeStyle = COLORS.amber
        ctx.lineWidth = 2
        ctx.setLineDash([5, 4])
        ctx.strokeRect(-w / 2 + 1.5, -h / 2 + 1.5, w - 3, h - 3)
        ctx.setLineDash([])
      }
      ctx.restore()
    }

    /** The blast itself. The wreckage is real bodies thrown by the physics -
     *  this is only the light and the smoke over the top of it, and it is
     *  over in half a second. */
    const drawBlast = (world: TruckWorld, t: number) => {
      if (t >= 1) return
      const { x, y } = world.chassis.position
      const fade = 1 - t
      ctx.save()

      // Shock ring.
      ctx.globalAlpha = fade * 0.9
      ctx.strokeStyle = COLORS.amber
      ctx.lineWidth = 5 * fade + 1
      ctx.beginPath()
      ctx.arc(x, y, 24 + t * 260, 0, Math.PI * 2)
      ctx.stroke()

      // Fireball, collapsing into smoke as it rises.
      const ballR = 34 + t * 90
      ctx.globalAlpha = fade * fade
      ctx.fillStyle = COLORS.amber
      ctx.beginPath()
      ctx.arc(x, y - t * 70, ballR, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = fade * 0.55
      ctx.fillStyle = COLORS.danger
      ctx.beginPath()
      ctx.arc(x, y - t * 70, ballR * 0.62, 0, Math.PI * 2)
      ctx.fill()

      ctx.globalAlpha = fade * 0.35
      ctx.fillStyle = COLORS.muted
      for (let i = 0; i < 7; i++) {
        const a = (i / 7) * Math.PI * 2
        ctx.beginPath()
        ctx.arc(
          x + Math.cos(a) * (30 + t * 120),
          y + Math.sin(a) * (22 + t * 60) - t * 110,
          16 + t * 34, 0, Math.PI * 2,
        )
        ctx.fill()
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
      // 'wrecked' steps too, without input: the debris is real physics and
      // has to fall somewhere.
      if (phase !== 'arrived' && phase !== 'failed') {
        const steps = Math.max(1, Math.round(elapsed / (1000 / 60)))
        for (let i = 0; i < steps; i++) {
          if (phase === 'driving') {
            drive(world, inputRef.current.throttle)
            if (inputRef.current.braking) brake(world)
          }
          // Rolling resistance and the hold that keeps a parked rig parked.
          // Applied in every live phase, not just while driving: with the
          // wheels frictionless it is the only thing stopping the truck
          // sliding off down a slope while the player is still loading it.
          coast(world)
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
      // A little light at the top. The tokens give one flat background
      // colour, so depth has to be added over it rather than picked from a
      // palette - and a translucent wash works in either theme, where a
      // second hard-coded colour would only work in one.
      const sky = ctx.createLinearGradient(0, 0, 0, VIEW.h * 0.7)
      sky.addColorStop(0, 'rgba(255,255,255,0.07)')
      sky.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.fillStyle = sky
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

      // Terrain, then the road laid on top of it. Two passes rather than one
      // fill: the earth and the surface you drive on are different things,
      // and the road edge is the line the player is actually reading when
      // they judge a washout.
      const floor = camY + VIEW.h / zoom + 400

      // Two ranges of hills behind the road, drawn from the route's own
      // heights at a lower frequency and scrolled slower than the ground.
      // Without them the truck reads as driving on a line in an empty void;
      // the parallax is what makes the road feel like it is somewhere.
      const drawRidge = (shift: number, lift: number, squash: number, tint: string) => {
        ctx.save()
        ctx.translate(camX * (1 - shift), 0)
        ctx.fillStyle = tint
        ctx.beginPath()
        ctx.moveTo(-VIEW.w, floor)
        for (let i = 0; i < route.heights.length; i += 3) {
          const h = route.heights[i]
          ctx.lineTo(
            i * SEGMENT_WIDTH * shift + camX * 0,
            BASE + (h - BASE) * squash - lift,
          )
        }
        ctx.lineTo(route.heights.length * SEGMENT_WIDTH, floor)
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      }
      drawRidge(0.35, 96, 0.5, 'rgba(255,255,255,0.045)')
      drawRidge(0.6, 44, 0.7, 'rgba(0,0,0,0.22)')

      const surface = new Path2D()
      surface.moveTo(0, route.heights[0])
      for (let i = 1; i < route.heights.length; i++) {
        surface.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }

      const earth = new Path2D()
      earth.moveTo(0, floor)
      for (let i = 0; i < route.heights.length; i++) {
        earth.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }
      earth.lineTo((route.heights.length - 1) * SEGMENT_WIDTH, floor)
      earth.closePath()
      ctx.fillStyle = grain
      ctx.fill(earth)
      // Subsoil: everything below a fixed depth goes darker, so the cut
      // through the ground at a washout reads as depth rather than as a
      // flat shape with a notch in it.
      ctx.save()
      ctx.clip(earth)
      const soil = ctx.createLinearGradient(0, camY, 0, floor)
      soil.addColorStop(0, 'rgba(0,0,0,0)')
      soil.addColorStop(0.35, 'rgba(0,0,0,0.35)')
      soil.addColorStop(1, 'rgba(0,0,0,0.6)')
      ctx.fillStyle = soil
      ctx.fill(earth)
      ctx.restore()

      // Asphalt.
      ctx.save()
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      ctx.strokeStyle = 'rgba(0,0,0,0.42)'
      ctx.lineWidth = 11
      ctx.stroke(surface)
      ctx.strokeStyle = 'rgba(255,255,255,0.16)'
      ctx.lineWidth = 1.5
      ctx.stroke(surface)
      ctx.restore()

      // Rubber left behind by hard braking - the friction the rig is using
      // made visible, and the clearest signal that a stop was not gentle.
      if (skids.length > 0) {
        ctx.save()
        ctx.strokeStyle = 'rgba(0,0,0,0.5)'
        ctx.lineWidth = 4
        ctx.lineCap = 'round'
        ctx.beginPath()
        for (const mark of skids) {
          ctx.moveTo(mark.x - 5, mark.y)
          ctx.lineTo(mark.x + 5, mark.y)
        }
        ctx.stroke()
        ctx.restore()
      }

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
      const drawTyre = (x: number, y: number, r: number, spin: number, tilt: number) => {
        ctx.save()
        ctx.translate(x, y)
        // Tyre.
        ctx.fillStyle = 'rgba(0,0,0,0.85)'
        ctx.beginPath()
        ctx.arc(0, 0, r, 0, Math.PI * 2)
        ctx.fill()
        ctx.save()
        ctx.rotate(spin)
        // Tread, as notches around the edge rather than a drawn ring: it is
        // the only thing at this size that makes the rotation readable.
        ctx.strokeStyle = 'rgba(255,255,255,0.16)'
        ctx.lineWidth = 2
        for (let i = 0; i < 10; i++) {
          const a = (i / 10) * Math.PI * 2
          ctx.beginPath()
          ctx.moveTo(Math.cos(a) * (r - 4), Math.sin(a) * (r - 4))
          ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r)
          ctx.stroke()
        }
        // Rim and spokes.
        ctx.fillStyle = COLORS.muted
        ctx.beginPath()
        ctx.arc(0, 0, r * 0.52, 0, Math.PI * 2)
        ctx.fill()
        ctx.strokeStyle = 'rgba(0,0,0,0.55)'
        ctx.lineWidth = 2.5
        for (let i = 0; i < 5; i++) {
          const a = (i / 5) * Math.PI * 2
          ctx.beginPath()
          ctx.moveTo(0, 0)
          ctx.lineTo(Math.cos(a) * r * 0.5, Math.sin(a) * r * 0.5)
          ctx.stroke()
        }
        ctx.restore()
        ctx.fillStyle = COLORS.ink
        ctx.beginPath()
        ctx.arc(0, 0, r * 0.17, 0, Math.PI * 2)
        ctx.fill()
        // Mudguard, which belongs to the body and so follows its pitch.
        ctx.rotate(tilt)
        ctx.strokeStyle = 'rgba(0,0,0,0.5)'
        ctx.lineWidth = 5
        ctx.beginPath()
        ctx.arc(0, 0, r + 5, Math.PI * 1.15, Math.PI * 1.95)
        ctx.stroke()
        ctx.restore()
      }

      if (world.debris.length > 0) {
        // What is left of it. Pieces are ordinary bodies, so they are drawn
        // like anything else.
        for (const piece of world.debris) {
          if (piece.circleRadius) {
            drawTyre(piece.position.x, piece.position.y, piece.circleRadius, piece.angle, 0)
          } else {
            drawBody(piece, COLORS.danger)
          }
        }
      } else {
        // The physics parts first, so the silhouette on screen is exactly the
        // shape the collisions use - then the detail over the top of it.
        // Muted rather than the brand green: a whole truck in the accent
        // colour was the loudest thing on the page by a wide margin.
        for (const part of world.chassis.parts.slice(1)) {
          if (part.label !== 'wheel') drawBody(part, COLORS.muted)
        }

        // Everything below is in the chassis rectangle's own frame: x runs
        // -125 to 125 along the rig, y is -13 to 13 through the frame rail,
        // and the deck surface sits at -21.
        //
        // It is reached through the BODY's angle, not the part's. Matter
        // rotates a part's vertices and position but never writes back
        // part.angle, which stays 0 for the life of the body - so detail
        // drawn with the part's own angle sat bolt upright while the rig
        // pitched underneath it, and the cab appeared to fall off.
        ctx.save()
        ctx.translate(world.chassis.position.x, world.chassis.position.y)
        ctx.rotate(world.chassis.angle)
        ctx.translate(world.hullOffset.x, world.hullOffset.y)

        // Deck planking.
        ctx.strokeStyle = 'rgba(0,0,0,0.28)'
        ctx.lineWidth = 1
        for (let x = -118; x < 52; x += 11) {
          ctx.beginPath()
          ctx.moveTo(x, -21)
          ctx.lineTo(x, -14)
          ctx.stroke()
        }
        // Frame rail, and the shadow the deck casts on it.
        ctx.fillStyle = 'rgba(0,0,0,0.38)'
        ctx.fillRect(-125, 6, 250, 7)
        ctx.fillStyle = 'rgba(0,0,0,0.2)'
        ctx.fillRect(-125, -13, 250, 3)

        // Cab: a sloped nose, a deep windscreen and a door line. This is
        // what makes it read as a truck rather than a plank on wheels.
        ctx.fillStyle = bodyColor
        ctx.beginPath()
        ctx.moveTo(54, -13)
        ctx.lineTo(54, -54)
        ctx.lineTo(102, -54)
        ctx.lineTo(124, -30)
        ctx.lineTo(124, -13)
        ctx.closePath()
        ctx.fill()
        // Windscreen and side glass.
        ctx.fillStyle = 'rgba(0,0,0,0.5)'
        ctx.beginPath()
        ctx.moveTo(78, -49)
        ctx.lineTo(99, -49)
        ctx.lineTo(115, -32)
        ctx.lineTo(78, -32)
        ctx.closePath()
        ctx.fill()
        ctx.fillRect(60, -49, 14, 17)
        // Door line and handle.
        ctx.strokeStyle = 'rgba(0,0,0,0.35)'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(76, -50)
        ctx.lineTo(76, -14)
        ctx.stroke()
        // Exhaust stack behind the cab.
        ctx.fillStyle = COLORS.muted
        ctx.fillRect(48, -62, 5, 42)
        // Lamp and grille.
        ctx.fillStyle = COLORS.amber
        ctx.beginPath()
        ctx.arc(119, -20, 3.5, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = 'rgba(0,0,0,0.3)'
        ctx.fillRect(112, -29, 12, 5)
        ctx.restore()

        for (const wheel of [world.rearWheel, world.frontWheel]) {
          const r = wheel.circleRadius || 20
          drawTyre(
            wheel.position.x, wheel.position.y, r,
            world.chassis.position.x / r, world.chassis.angle,
          )
        }
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
          if (reachable) {
            // The instruction goes on the thing it applies to. A button
            // somewhere else on screen makes the player look away from the
            // item they are trying to pick up.
            ctx.setLineDash([])
            ctx.globalAlpha = 1
            ctx.fillStyle = COLORS.accent
            ctx.font = '600 12px system-ui, sans-serif'
            ctx.textAlign = 'center'
            ctx.fillText(
              'pick up',
              entry.body.position.x,
              entry.body.position.y - entry.h / 2 - 14,
            )
          }
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
        // The blast is brief; the debris then falls for the rest of WRECK_MS.
        drawBlast(world, Math.min(1, (now - wreckedAt.current) / 620))
      }

      ctx.restore()

      // A white-out over everything, for the first few frames only.
      if (phase === 'wrecked') {
        const flash = 1 - Math.min(1, (now - wreckedAt.current) / 180)
        if (flash > 0) {
          ctx.save()
          ctx.globalAlpha = flash * 0.75
          ctx.fillStyle = COLORS.amber
          ctx.fillRect(0, 0, VIEW.w, VIEW.h)
          ctx.restore()
        }
      }

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

        if (world.braking && Math.abs(world.chassis.velocity.x) > 1.2) {
          for (const wheel of [world.rearWheel, world.frontWheel]) {
            skids.push({ x: wheel.position.x, y: wheel.position.y + (wheel.circleRadius || 20) })
          }
          if (skids.length > 500) skids.splice(0, skids.length - 500)
        }
        world.braking = false

        if (world.truckDamage >= 1) {
          wreckedAt.current = now
          explodeTruck(world)
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
          onPointerUp={(e) => {
            if (aiming) {
              aimAt(e.clientX)
              placeHere()
            } else if (phase === 'driving') {
              // Point at what you dropped to pick it up - a click, or a tap.
              pickUpAt(e.clientX, e.clientY)
            }
          }}
        />

        {phase === 'driving' && (
          <div className="tg-progress" aria-hidden="true">
            <span style={{ width: `${progress * 100}%` }} />
          </div>
        )}

        {phase === 'driving' && canRecover && (
          <div className="tg-recover">
            Stopped beside it &mdash; tap the load to put it back on
            <span className="tg-recover-key">, or press E</span>
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
          : 'Arrows or A/D to drive · Space to brake · stop beside anything you drop and click it'}
      </p>
    </div>
  )
}
