import { useCallback, useEffect, useRef, useState } from 'react'
import Matter from 'matter-js'
import {
  generateRoute, mulberry32, SEGMENT_WIDTH, BASE_GROUND_Y as BASE,
  type Crate, type Route,
} from './route'

/** Matches RUNOFF in engine.ts - the apron of road past each end. */
const RUNOFF = 900
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

type Phase = 'loading' | 'driving' | 'reloading' | 'arrived' | 'failed' | 'wrecked' | 'stranded'

const VIEW = { w: 900, h: 520 }

/** Keyboard nudge per press while aiming - fine enough to thread a gap. */
const AIM_STEP = 4

/**
 * How long an ending plays before the result panel takes over.
 *
 * Both are real physics rather than a canned animation - the rig comes apart
 * into loose bodies, and a load being written off shatters into its own - so
 * covering them the instant the outcome is decided threw away the only part
 * the player was watching.
 */
const WRECK_MS = 2400
const LOSS_MS = 1600

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
  const [fuel, setFuel] = useState(1)
  const [canRecover, setCanRecover] = useState(false)
  // An ending with something to watch holds the panel back until it has
  // been watched.
  const [endingPlayed, setEndingPlayed] = useState(false)
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
  // setPhase does not take effect until React re-renders, and the draw loop
  // keeps running against the old value until then - so an ending whose
  // condition stays true (out of fuel, say) would submit the same run once
  // per frame in the meantime. The server rejects a re-used ticket, so this
  // was harmless, but it was a burst of pointless requests.
  const finished = useRef(false)

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
    finished.current = false
    setPayout(0)
    setProgress(0)
    setCondition(1)
    setFuel(1)
    setCanRecover(false)
    setEndingPlayed(false)
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
    // The same pixels-per-world-unit on both axes, because the frame is
    // scaled off the width and the height simply follows.
    const perPixel = VIEW.w / (rect.width * cam.zoom)
    return {
      x: (clientX - rect.left) * perPixel + cam.x,
      y: (clientY - rect.top) * perPixel + cam.y,
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

    // Effects the physics has asked for, stamped with the time they arrived
    // so they can fade. The engine has no clock worth trusting for
    // animation, so it reports what happened and this decides how long it
    // is on screen for.
    const effects: { kind: string; x: number; y: number; at: number }[] = []

    /** Ground height at a world x, interpolated between samples. */
    const groundAt = (x: number) => {
      const t = x / SEGMENT_WIDTH
      const i = Math.max(0, Math.min(route.heights.length - 2, Math.floor(t)))
      const f = Math.max(0, Math.min(1, t - i))
      return route.heights[i] * (1 - f) + route.heights[i + 1] * f
    }

    // Trees, from the route's own seed so they are in the same place every
    // time it is played and never shimmer between frames. Two bands at
    // different parallax depths - one behind the ridges, one just off the
    // verge - which is most of what sells the distance.
    const treeRand = mulberry32((route.seed ^ 0x5eed) >>> 0)
    const trees: { x: number; scale: number; depth: number; lean: number }[] = []
    for (let i = 0; i < 150; i++) {
      trees.push({
        x: treeRand() * route.heights.length * SEGMENT_WIDTH,
        scale: 0.55 + treeRand() * 0.85,
        depth: treeRand() < 0.55 ? 0.55 : 0.8,
        lean: (treeRand() - 0.5) * 0.24,
      })
    }

    /** Birds, because an empty sky over a long road is the emptiest part of
     *  it. They cross slowly, well behind everything else, and flap on their
     *  own clocks so they never move as a block. */
    const birds = Array.from({ length: 9 }, () => ({
      x: treeRand() * route.heights.length * SEGMENT_WIDTH,
      y: BASE - 150 - treeRand() * 190,
      speed: 0.35 + treeRand() * 0.5,
      scale: 0.7 + treeRand() * 0.7,
      phase: treeRand() * Math.PI * 2,
    }))

    const drawBirds = (now: number, from: number, to: number) => {
      const span = route.heights.length * SEGMENT_WIDTH
      ctx.strokeStyle = 'rgba(0,0,0,0.45)'
      ctx.lineWidth = 1.6
      for (const bird of birds) {
        // Wrapped rather than respawned, so a bird never pops into being in
        // the middle of the screen.
        const x = ((bird.x + (now / 1000) * bird.speed * 26) % (span + 400)) - 200
        if (x < from - 40 || x > to + 40) continue
        const beat = Math.sin(now / 260 + bird.phase)
        const w = 6 * bird.scale
        const lift = beat * 2.4 * bird.scale
        const y = bird.y + Math.sin(now / 1700 + bird.phase) * 9
        ctx.beginPath()
        ctx.moveTo(x - w, y + lift)
        ctx.quadraticCurveTo(x - w * 0.4, y - lift * 0.8, x, y)
        ctx.quadraticCurveTo(x + w * 0.4, y - lift * 0.8, x + w, y + lift)
        ctx.stroke()
      }
    }

    const drawTree = (x: number, groundY: number, scale: number, tint: string) => {
      const h = 58 * scale
      ctx.save()
      ctx.translate(x, groundY)
      ctx.fillStyle = tint
      // Trunk.
      ctx.fillRect(-2 * scale, -h * 0.42, 4 * scale, h * 0.42)
      // Three stacked tiers - a conifer silhouette, which stays readable at
      // any size and needs no detail to be recognisable.
      for (let tier = 0; tier < 3; tier++) {
        const top = -h + (h * 0.28) * tier
        const spread = (10 + tier * 6) * scale
        ctx.beginPath()
        ctx.moveTo(0, top)
        ctx.lineTo(spread, top + h * 0.36)
        ctx.lineTo(-spread, top + h * 0.36)
        ctx.closePath()
        ctx.fill()
      }
      ctx.restore()
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

    const drawCargo = (entry: CargoBody, world: TruckWorld) => {
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

      // Soaked: darker, and running. A wet load is heavier and the deck it
      // is sitting on has lost its grip, so it needs to be obvious at a
      // glance which items took the spill.
      if (entry.wetUntil > world.engine.timing.timestamp) {
        ctx.fillStyle = 'rgba(38,86,132,0.42)'
        ctx.fillRect(-w / 2, -h / 2, w, h)
        ctx.strokeStyle = 'rgba(150,205,255,0.55)'
        ctx.lineWidth = 1.5
        for (let i = 0; i < 3; i++) {
          const dx = -w / 2 + (w * (i + 1)) / 4
          ctx.beginPath()
          ctx.moveTo(dx, h / 2 - 2)
          ctx.lineTo(dx, h / 2 + 3 + (i % 2) * 2)
          ctx.stroke()
        }
      }

      // Damage.
      //
      // A tint alone was not enough - at a third gone the amber wash was
      // sitting at 18% opacity over a brown crate, which is invisible.
      // Stronger now, and paired with something that is not a colour at all:
      // cracks that spread across the face as it goes. Colour is the fastest
      // read when you are watching the road, but it is also the thing that
      // disappears against the wrong material, and the two together survive
      // both.
      if (entry.damage > 0.02) {
        ctx.fillStyle = entry.damage > 0.5
          ? `rgba(210,58,46,${0.3 + entry.damage * 0.55})`
          : `rgba(224,150,44,${0.22 + entry.damage * 0.9})`
        ctx.fillRect(-w / 2, -h / 2, w, h)

        // Damage looks like what the thing is made of.
        //
        // The first version chipped corners off everything, which is right
        // for a timber crate and plainly wrong for a steel drum - a drum
        // does not lose its corners, it dents, buckles at the hoops and
        // splits at a seam. Seeing square bites taken out of a barrel was
        // the giveaway.
        if (entry.crate.kind === 'drum') {
          const dents = Math.round(entry.damage * 4)
          for (let i = 0; i < dents; i++) {
            // Pressed in from alternating sides, along the drum's long axis.
            const along = (((i * 41) % 100) / 100 - 0.5) * (h >= w ? h : w) * 0.7
            const side = i % 2 ? 1 : -1
            const depth = Math.min(w, h) * (0.16 + entry.damage * 0.16)
            ctx.fillStyle = skin.dark
            ctx.beginPath()
            if (h >= w) {
              ctx.moveTo((side * w) / 2, along - depth)
              ctx.quadraticCurveTo((side * w) / 2 - side * depth, along, (side * w) / 2, along + depth)
            } else {
              ctx.moveTo(along - depth, (side * h) / 2)
              ctx.quadraticCurveTo(along, (side * h) / 2 - side * depth, along + depth, (side * h) / 2)
            }
            ctx.closePath()
            ctx.fill()
          }

          // A split seam once it is properly beaten up, and a weep from it.
          // Not a running stream: the drum has not burst yet, and drawing
          // one would promise a spill that has not happened.
          if (entry.damage > 0.55) {
            ctx.strokeStyle = 'rgba(0,0,0,0.7)'
            ctx.lineWidth = 2
            ctx.beginPath()
            if (h >= w) {
              ctx.moveTo(-w * 0.1, -h * 0.2)
              ctx.lineTo(w * 0.16, h * 0.1)
            } else {
              ctx.moveTo(-w * 0.2, -h * 0.1)
              ctx.lineTo(w * 0.1, h * 0.16)
            }
            ctx.stroke()
            if (entry.crate.hazard !== 'none') {
              ctx.fillStyle = entry.crate.hazard === 'flammable'
                ? 'rgba(178,58,40,0.5)'
                : 'rgba(58,110,158,0.55)'
              ctx.beginPath()
              ctx.ellipse(w * 0.1, h * 0.28, w * 0.16, h * 0.1, 0, 0, Math.PI * 2)
              ctx.fill()
            }
          }
        } else {
          // Timber: it loses corners and splits along its boards. Derived
          // from the index rather than random, so nothing crawls between
          // frames.
          const bites = Math.round(entry.damage * 4)
          ctx.fillStyle = COLORS.sky
          for (let i = 0; i < bites; i++) {
            const corner = i % 4
            const cx = corner < 2 ? -w / 2 : w / 2
            const cy = corner % 2 === 0 ? -h / 2 : h / 2
            const bx = Math.min(w * 0.34, 5 + i * 3) * (corner < 2 ? 1 : -1)
            const by = Math.min(h * 0.34, 4 + i * 3) * (corner % 2 === 0 ? 1 : -1)
            ctx.beginPath()
            ctx.moveTo(cx, cy)
            ctx.lineTo(cx + bx, cy)
            ctx.lineTo(cx, cy + by)
            ctx.closePath()
            ctx.fill()
          }
          const splits = Math.round(entry.damage * 3)
          ctx.strokeStyle = 'rgba(0,0,0,0.55)'
          ctx.lineWidth = 1
          for (let i = 0; i < splits; i++) {
            const y = -h / 2 + (h * (i + 1)) / (splits + 1)
            const from = -w / 2 + ((i * 29) % 40) / 100 * w
            ctx.beginPath()
            ctx.moveTo(from, y)
            ctx.lineTo(from + w * 0.5, y)
            ctx.moveTo(from + w * 0.2, y)
            ctx.lineTo(from + w * 0.34, y - 2.5)
            ctx.stroke()
          }
        }
      }

      if (entry.crate.fragile) {
        ctx.strokeStyle = COLORS.amber
        ctx.lineWidth = 2
        ctx.setLineDash([5, 4])
        ctx.strokeRect(-w / 2 + 1.5, -h / 2 + 1.5, w - 3, h - 3)
        ctx.setLineDash([])
      }

      // Placard.
      //
      // The flammable one follows the real thing: DOT Class 3 is a red
      // diamond with a white flame and a 3 at the bottom, and it is on the
      // drum for the same reason it would be on a real one - so you know
      // before you load it what it will do if you break it. The liquid mark
      // is deliberately NOT placard-shaped, because there is no real class
      // it corresponds to and dressing it up as one would be a lie about
      // something people actually have to know.
      if (entry.crate.hazard === 'flammable') {
        const r = Math.min(w, h) * 0.3
        ctx.save()
        ctx.rotate(Math.PI / 4)
        ctx.fillStyle = '#c8261d'
        ctx.fillRect(-r, -r, r * 2, r * 2)
        ctx.strokeStyle = 'rgba(255,255,255,0.85)'
        ctx.lineWidth = 1
        ctx.strokeRect(-r + 2, -r + 2, r * 2 - 4, r * 2 - 4)
        ctx.restore()
        // Flame, upright rather than on the diamond's axis.
        ctx.fillStyle = '#fff'
        ctx.beginPath()
        ctx.moveTo(0, -r * 0.62)
        ctx.quadraticCurveTo(r * 0.42, -r * 0.05, 0, r * 0.5)
        ctx.quadraticCurveTo(-r * 0.42, -r * 0.05, 0, -r * 0.62)
        ctx.fill()
      } else if (entry.crate.hazard === 'liquid') {
        const r = Math.min(w, h) * 0.26
        ctx.fillStyle = '#2f5f8f'
        ctx.beginPath()
        ctx.arc(0, 0, r, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = 'rgba(255,255,255,0.9)'
        ctx.beginPath()
        ctx.moveTo(0, -r * 0.62)
        ctx.quadraticCurveTo(r * 0.55, r * 0.18, 0, r * 0.6)
        ctx.quadraticCurveTo(-r * 0.55, r * 0.18, 0, -r * 0.62)
        ctx.fill()
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
      // The losing endings keep stepping, without input, until their
      // wreckage has landed - it is real physics and has to fall somewhere.
      const settling = (phase === 'wrecked' || phase === 'failed') && !endingPlayed
      if (phase === 'driving' || phase === 'loading' || phase === 'reloading' || settling) {
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

      // How much world fits vertically, worked out from the canvas rather
      // than assumed.
      //
      // Everything scales off the WIDTH, so on a tall canvas - full screen,
      // most of all - the drawing ran past VIEW.h and the extra was filled
      // by the ground polygon, which is why the earth was taking up half the
      // screen. The camera now frames against the real height, so the road
      // sits at the same place on screen whatever shape the window is.
      const viewH = (VIEW.w * rect.height) / rect.width

      ctx.fillStyle = COLORS.sky
      ctx.fillRect(0, 0, VIEW.w, viewH)
      // A little light at the top. The tokens give one flat background
      // colour, so depth has to be added over it rather than picked from a
      // palette - and a translucent wash works in either theme, where a
      // second hard-coded colour would only work in one.
      const sky = ctx.createLinearGradient(0, 0, 0, viewH * 0.7)
      sky.addColorStop(0, 'rgba(255,255,255,0.07)')
      sky.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.fillStyle = sky
      ctx.fillRect(0, 0, VIEW.w, viewH)

      // Camera trails the truck, keeping it left-of-centre so the road ahead
      // is what the player is actually looking at. Aiming pulls in close
      // instead: the deck is what is being looked at, and placing an item to
      // the pixel is impossible when the whole deck is 174px wide on screen.
      const closeUp = phase === 'loading' || phase === 'reloading'
      const zoom = closeUp ? 2 : 1
      const camX = closeUp
        ? world.chassis.position.x - VIEW.w / (2 * zoom)
        : Math.max(0, world.chassis.position.x - VIEW.w * 0.35)
      // The road sits low in the frame: three quarters of the way down, so
      // what the player is looking at is mostly the sky ahead and the load,
      // not the dirt under it.
      const camY = closeUp
        ? world.chassis.position.y - (viewH * 0.6) / zoom
        : world.chassis.position.y - viewH * 0.74
      cameraRef.current = { x: camX, y: camY, zoom }
      ctx.save()
      if (zoom !== 1) ctx.scale(zoom, zoom)
      ctx.translate(-camX, -camY)

      // Terrain, then the road laid on top of it. Two passes rather than one
      // fill: the earth and the surface you drive on are different things,
      // and the road edge is the line the player is actually reading when
      // they judge a washout.
      const floor = camY + viewH / zoom + 400

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
      drawBirds(now, camX, camX + VIEW.w / zoom)
      drawRidge(0.35, 96, 0.5, 'rgba(255,255,255,0.045)')
      drawRidge(0.6, 44, 0.7, 'rgba(0,0,0,0.22)')

      // Treeline. Placed against the road's own profile so it follows the
      // land, and drawn before the ground so the trunks are planted in it
      // rather than standing on top of it.
      const view = VIEW.w / zoom
      for (const tree of trees) {
        const drawX = tree.x * tree.depth + camX * (1 - tree.depth)
        if (drawX < camX - 90 || drawX > camX + view + 90) continue
        ctx.save()
        ctx.translate(drawX, 0)
        ctx.rotate(tree.lean * 0.12)
        ctx.translate(-drawX, 0)
        drawTree(
          drawX,
          groundAt(tree.x) - (tree.depth < 0.7 ? 34 : 6),
          tree.scale * (tree.depth < 0.7 ? 0.8 : 1),
          tree.depth < 0.7 ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.45)',
        )
        ctx.restore()
      }

      const surface = new Path2D()
      surface.moveTo(-RUNOFF, route.heights[0])
      for (let i = 0; i < route.heights.length; i++) {
        surface.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }
      surface.lineTo(
        (route.heights.length - 1) * SEGMENT_WIDTH + RUNOFF,
        route.heights[route.heights.length - 1],
      )

      const lastX = (route.heights.length - 1) * SEGMENT_WIDTH
      const earth = new Path2D()
      earth.moveTo(-RUNOFF, floor)
      earth.lineTo(-RUNOFF, route.heights[0])
      for (let i = 0; i < route.heights.length; i++) {
        earth.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }
      earth.lineTo(lastX + RUNOFF, route.heights[route.heights.length - 1])
      earth.lineTo(lastX + RUNOFF, floor)
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

      // The two ends of the job.
      //
      // They are deliberately different buildings, because in freight they
      // are different places. Loading is at a warehouse dock: a raised
      // platform at trailer-deck height, roughly 48-52 inches, so a forklift
      // can run straight out onto the bed. Flatbed freight is very often
      // delivered somewhere with no dock at all - a yard, a site, a
      // ground-level gate - and unloaded from the side. So: a dock at the
      // start, a fenced yard at the finish.
      /**
       * The warehouse the load came out of.
       *
       * Drawn to the same face the physics wall is at, so reversing off the
       * dock stops against the building the player can see rather than
       * against nothing. A dock platform sits at trailer-deck height - 48 to
       * 52 inches, so a forklift runs straight out onto the bed - which is
       * why the deck of the truck lines up with the floor of the shed.
       */
      const drawDepot = () => {
        const g = groundAt(0)
        const face = 60
        const back = face - 460
        const eaves = g - 168
        ctx.save()

        // Shell, with a shallow pitch.
        ctx.fillStyle = 'rgba(0,0,0,0.62)'
        ctx.beginPath()
        ctx.moveTo(back, g)
        ctx.lineTo(back, eaves)
        ctx.lineTo(back + 230, eaves - 34)
        ctx.lineTo(face, eaves)
        ctx.lineTo(face, g)
        ctx.closePath()
        ctx.fill()
        // Roof edge catching the light.
        ctx.strokeStyle = 'rgba(255,255,255,0.14)'
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.moveTo(back - 6, eaves)
        ctx.lineTo(back + 230, eaves - 34)
        ctx.lineTo(face + 6, eaves)
        ctx.stroke()

        // Corrugated wall panels.
        ctx.strokeStyle = 'rgba(255,255,255,0.05)'
        ctx.lineWidth = 1
        for (let x = back + 14; x < face; x += 16) {
          ctx.beginPath()
          ctx.moveTo(x, g)
          ctx.lineTo(x, eaves + 12)
          ctx.stroke()
        }

        // Dock doors, at deck height, with a lit one at the end.
        const doorTop = g - 108
        for (let i = 0; i < 3; i++) {
          const x = back + 40 + i * 120
          ctx.fillStyle = i === 2 ? 'rgba(224,184,84,0.16)' : 'rgba(255,255,255,0.08)'
          ctx.fillRect(x, doorTop, 84, 108)
          ctx.strokeStyle = 'rgba(0,0,0,0.5)'
          ctx.lineWidth = 1
          for (let y = doorTop + 8; y < g; y += 12) {
            ctx.beginPath()
            ctx.moveTo(x, y)
            ctx.lineTo(x + 84, y)
            ctx.stroke()
          }
          ctx.strokeStyle = 'rgba(255,255,255,0.12)'
          ctx.lineWidth = 2
          ctx.strokeRect(x, doorTop, 84, 108)
        }

        // Canopy over the dock, and the rubber bumpers the trailer backs on
        // to. This is the part the truck is actually parked against.
        ctx.fillStyle = 'rgba(0,0,0,0.5)'
        ctx.fillRect(face - 12, g - 132, 34, 8)
        ctx.fillStyle = COLORS.muted
        ctx.fillRect(face - 6, g - 56, 8, 6)
        ctx.fillStyle = 'rgba(0,0,0,0.85)'
        for (const dy of [0, 26]) ctx.fillRect(face - 2, g - 46 + dy, 7, 18)

        // Sign band.
        ctx.fillStyle = 'rgba(255,255,255,0.1)'
        ctx.fillRect(back + 30, eaves + 16, 130, 16)
        ctx.restore()
      }

      /**
       * The consignee at the far end.
       *
       * A different building on purpose, because in freight it is a
       * different place: flatbed loads are very often delivered somewhere
       * with no dock at all, and unloaded from the side by forklift or
       * crane. So this is a ground-level receiving building in a fenced
       * yard, square on to the road, rather than a second dock.
       */
      const drawDropSite = () => {
        const x = world.finishX
        const g = groundAt(x)
        ctx.save()

        // Fence across the yard, in front of the building.
        ctx.strokeStyle = 'rgba(255,255,255,0.14)'
        ctx.lineWidth = 1
        for (let px = x - 30; px < x + 200; px += 15) {
          ctx.beginPath()
          ctx.moveTo(px, groundAt(px) - 62)
          ctx.lineTo(px, groundAt(px))
          ctx.stroke()
        }
        ctx.strokeStyle = 'rgba(255,255,255,0.26)'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(x - 30, groundAt(x - 30) - 62)
        for (let px = x - 30; px < x + 200; px += 20) ctx.lineTo(px, groundAt(px) - 62)
        ctx.stroke()

        // The building itself, facing the road. Its face is where the wall
        // in the physics is, so the rig arrives and stops at the door.
        const face = x + 205
        const backEdge = face + 240
        const eaves = g - 190
        ctx.fillStyle = 'rgba(0,0,0,0.66)'
        ctx.fillRect(face, eaves, backEdge - face, g - eaves)
        // Parapet.
        ctx.fillStyle = 'rgba(255,255,255,0.09)'
        ctx.fillRect(face - 8, eaves - 12, backEdge - face + 16, 14)

        // A wide roller shutter, open, with the yard lit behind it.
        const doorW = 118
        ctx.fillStyle = 'rgba(224,184,84,0.14)'
        ctx.fillRect(face + 26, g - 130, doorW, 130)
        ctx.strokeStyle = 'rgba(255,255,255,0.16)'
        ctx.lineWidth = 2
        ctx.strokeRect(face + 26, g - 130, doorW, 130)
        ctx.fillStyle = 'rgba(255,255,255,0.1)'
        ctx.fillRect(face + 26, g - 130, doorW, 22)
        ctx.strokeStyle = 'rgba(0,0,0,0.45)'
        ctx.lineWidth = 1
        for (let y = g - 126; y < g - 108; y += 5) {
          ctx.beginPath()
          ctx.moveTo(face + 26, y)
          ctx.lineTo(face + 26 + doorW, y)
          ctx.stroke()
        }

        // Office windows alongside, and a sign over the door.
        ctx.fillStyle = 'rgba(224,184,84,0.18)'
        for (let i = 0; i < 3; i++) ctx.fillRect(face + 160 + i * 26, g - 116, 18, 24)
        ctx.fillStyle = 'rgba(255,255,255,0.12)'
        ctx.fillRect(face + 30, g - 156, 110, 15)

        // Material stacked in the yard, waiting to go out.
        ctx.fillStyle = 'rgba(0,0,0,0.42)'
        for (let i = 0; i < 3; i++) ctx.fillRect(x + 96, g - 12 - i * 11, 58, 9)
        ctx.restore()
      }

      drawDepot()
      drawDropSite()

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
          // 'cab' is excluded because the cab is drawn by hand below; the
          // part exists so freight can land on it, not to be looked at.
          if (part.label !== 'wheel' && part.label !== 'cab') drawBody(part, COLORS.muted)
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

        // Cab.
        //
        // Cab-over: tall, short-nosed, sat over the front axle. The deck
        // starts at x = 54 and everything behind that line is freight, so
        // there is only 71px of nose to work with - and a tractor cab stands
        // about twice the height of a flatbed deck, which puts the roof at
        // y = -84. Those two facts together only describe one shape, and it
        // happens to be a real and common one, chosen by real manufacturers
        // for the same reason: cab length is deck length you do not get.
        const CAB_BACK = 54
        const CAB_FRONT = 125
        const CAB_ROOF = -84

        // Shell, with the roof drawn in slightly at the front so it is not a
        // plain box.
        ctx.fillStyle = bodyColor
        ctx.beginPath()
        ctx.moveTo(CAB_BACK, -13)
        ctx.lineTo(CAB_BACK, CAB_ROOF + 6)
        ctx.quadraticCurveTo(CAB_BACK, CAB_ROOF, CAB_BACK + 9, CAB_ROOF)
        ctx.lineTo(CAB_FRONT - 12, CAB_ROOF + 2)
        ctx.quadraticCurveTo(CAB_FRONT - 2, CAB_ROOF + 4, CAB_FRONT, CAB_ROOF + 14)
        ctx.lineTo(CAB_FRONT, -13)
        ctx.closePath()
        ctx.fill()

        // Sun visor over the screen, and the roof deflector behind it - the
        // two things that make a working truck look like one rather than
        // like a van.
        ctx.fillStyle = 'rgba(0,0,0,0.42)'
        ctx.beginPath()
        ctx.moveTo(CAB_FRONT - 34, CAB_ROOF + 3)
        ctx.lineTo(CAB_FRONT + 3, CAB_ROOF + 9)
        ctx.lineTo(CAB_FRONT + 3, CAB_ROOF + 14)
        ctx.lineTo(CAB_FRONT - 34, CAB_ROOF + 10)
        ctx.closePath()
        ctx.fill()
        ctx.fillStyle = 'rgba(255,255,255,0.14)'
        ctx.beginPath()
        ctx.moveTo(CAB_BACK + 2, CAB_ROOF - 1)
        ctx.lineTo(CAB_FRONT - 30, CAB_ROOF - 15)
        ctx.lineTo(CAB_FRONT - 30, CAB_ROOF - 1)
        ctx.closePath()
        ctx.fill()

        // Glass: a deep screen up front and a door window behind the pillar.
        ctx.fillStyle = 'rgba(12,20,28,0.72)'
        ctx.beginPath()
        ctx.moveTo(96, CAB_ROOF + 14)
        ctx.lineTo(CAB_FRONT - 3, CAB_ROOF + 18)
        ctx.lineTo(CAB_FRONT - 3, CAB_ROOF + 44)
        ctx.lineTo(96, CAB_ROOF + 44)
        ctx.closePath()
        ctx.fill()
        ctx.fillRect(66, CAB_ROOF + 16, 24, 26)
        // A highlight across the glass, so it reads as glass.
        ctx.fillStyle = 'rgba(255,255,255,0.1)'
        ctx.beginPath()
        ctx.moveTo(98, CAB_ROOF + 40)
        ctx.lineTo(CAB_FRONT - 5, CAB_ROOF + 22)
        ctx.lineTo(CAB_FRONT - 5, CAB_ROOF + 28)
        ctx.lineTo(98, CAB_ROOF + 44)
        ctx.closePath()
        ctx.fill()

        // Body stripe along the doors, in the brand colour rather than the
        // whole cab being it.
        ctx.fillStyle = COLORS.accent
        ctx.fillRect(CAB_BACK + 3, -34, 66, 5)

        // Door, handle and the step under it.
        ctx.strokeStyle = 'rgba(0,0,0,0.45)'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(93, CAB_ROOF + 10)
        ctx.lineTo(93, -14)
        ctx.moveTo(62, CAB_ROOF + 12)
        ctx.lineTo(62, -14)
        ctx.stroke()
        ctx.fillStyle = 'rgba(0,0,0,0.35)'
        ctx.fillRect(70, -26, 16, 3)
        ctx.fillStyle = COLORS.muted
        ctx.fillRect(68, -8, 22, 3)

        // Grille, bumper and lamps.
        ctx.fillStyle = 'rgba(0,0,0,0.4)'
        ctx.fillRect(CAB_FRONT - 15, -40, 15, 18)
        ctx.fillStyle = COLORS.muted
        for (let i = 0; i < 4; i++) ctx.fillRect(CAB_FRONT - 14, -38 + i * 4, 13, 1.5)
        ctx.fillRect(CAB_FRONT - 18, -18, 20, 7)
        ctx.fillStyle = COLORS.amber
        ctx.beginPath()
        ctx.arc(CAB_FRONT - 8, -22, 3.2, 0, Math.PI * 2)
        ctx.fill()

        // Mirror arm and the stack behind the cab.
        ctx.strokeStyle = COLORS.muted
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(CAB_FRONT - 8, CAB_ROOF + 20)
        ctx.lineTo(CAB_FRONT + 7, CAB_ROOF + 15)
        ctx.stroke()
        ctx.fillStyle = COLORS.muted
        ctx.fillRect(CAB_BACK - 6, CAB_ROOF - 18, 6, 70)
        ctx.fillStyle = 'rgba(0,0,0,0.3)'
        ctx.fillRect(CAB_BACK - 7, CAB_ROOF - 18, 8, 4)
        ctx.restore()

        for (const wheel of [world.rearWheel, world.frontWheel]) {
          const r = wheel.circleRadius || 20
          drawTyre(
            wheel.position.x, wheel.position.y, r,
            world.chassis.position.x / r, world.chassis.angle,
          )
        }
      }

      // Freight that has come apart. Drawn under the intact load, so a
      // stack still reads clearly over its own wreckage.
      for (const shard of world.shards) {
        const skin = MATERIAL[shard.kind]
        ctx.save()
        ctx.translate(shard.body.position.x, shard.body.position.y)
        ctx.rotate(shard.body.angle)
        ctx.fillStyle = skin.base
        const v = shard.body.vertices
        ctx.beginPath()
        ctx.moveTo(v[0].x - shard.body.position.x, v[0].y - shard.body.position.y)
        for (let i = 1; i < v.length; i++) {
          ctx.lineTo(v[i].x - shard.body.position.x, v[i].y - shard.body.position.y)
        }
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      }

      // Anything the physics wants shown once. Drained rather than read, so
      // an effect cannot fire twice.
      while (world.events.length > 0) {
        const event = world.events.shift()
        if (event) effects.push({ ...event, at: now })
      }
      for (let i = effects.length - 1; i >= 0; i--) {
        const fx = effects[i]
        const life = fx.kind === 'blast' ? 700 : fx.kind === 'spill' ? 1400 : 450
        const t = (now - fx.at) / life
        if (t >= 1) {
          effects.splice(i, 1)
          continue
        }
        ctx.save()
        if (fx.kind === 'blast') {
          ctx.globalAlpha = (1 - t) ** 1.5
          ctx.fillStyle = COLORS.amber
          ctx.beginPath()
          ctx.arc(fx.x, fx.y - t * 40, 22 + t * 120, 0, Math.PI * 2)
          ctx.fill()
          ctx.globalAlpha = (1 - t) * 0.6
          ctx.fillStyle = COLORS.danger
          ctx.beginPath()
          ctx.arc(fx.x, fx.y - t * 40, (22 + t * 120) * 0.6, 0, Math.PI * 2)
          ctx.fill()
        } else if (fx.kind === 'spill') {
          // A pool spreading out from where it burst.
          ctx.globalAlpha = 0.5 * (1 - t * 0.4)
          ctx.fillStyle = '#3f6f9c'
          ctx.beginPath()
          ctx.ellipse(fx.x, fx.y + 6, 20 + t * 70, 5 + t * 5, 0, 0, Math.PI * 2)
          ctx.fill()
        } else {
          ctx.globalAlpha = (1 - t) * 0.55
          ctx.strokeStyle = COLORS.muted
          ctx.lineWidth = 2
          for (let k = 0; k < 6; k++) {
            const a = (k / 6) * Math.PI * 2
            ctx.beginPath()
            ctx.arc(fx.x + Math.cos(a) * (12 + t * 46), fx.y + Math.sin(a) * (8 + t * 30) - t * 18,
              5 + t * 9, 0, Math.PI * 2)
            ctx.stroke()
          }
        }
        ctx.restore()
      }

      const withinReach = phase === 'driving' ? recoverableCargo(world) : []
      for (const entry of world.cargo) {
        if (entry.state === 'gone') continue
        drawCargo(entry, world)
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
          ctx.fillRect(0, 0, VIEW.w, viewH)
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
          if (finished.current) return
          finished.current = true
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

        setFuel(world.fuel)

        if (finished.current) {
          // Nothing left to decide; the phase change is on its way.
        } else if (world.fuel <= 0 && Math.abs(world.chassis.velocity.x) < 0.2) {
          // Stops where it stands. The load never arrived, so it pays
          // nothing - the same as losing it, because that is what happened.
          setPhase('stranded')
          setPayout(0)
          submit({ payout: 0, delivered: 0, lost: world.cargo.length })
        } else if (world.truckDamage >= 1) {
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
  }, [route, phase, onFinish, ticket, endingPlayed])

  // A wreck and a total loss both have wreckage to watch; arriving and
  // running dry do not, so those show their panel straight away.
  useEffect(() => {
    if (phase !== 'wrecked' && phase !== 'failed') return
    const timer = setTimeout(
      () => setEndingPlayed(true), phase === 'wrecked' ? WRECK_MS : LOSS_MS,
    )
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
  const fuelPct = Math.max(0, Math.round(fuel * 100))

  return (
    <div className="tg" ref={shellRef}>
      <div className="tg-hud">
        <span className="tg-stat">Loaded <b>{placed}/{route.crates.length}</b></span>
        <span className="tg-stat">On board <b>${payout.toLocaleString('en-US')}</b></span>
        <span className="tg-stat is-muted">Full load <b>${route.maxPayout.toLocaleString('en-US')}</b></span>
        <span className={`tg-stat${conditionPct <= 35 ? ' is-critical' : conditionPct <= 70 ? ' is-warn' : ''}`}>
          Rig <b>{conditionPct}%</b>
        </span>
        <span className={`tg-stat${fuelPct <= 15 ? ' is-critical' : fuelPct <= 35 ? ' is-warn' : ''}`}>
          Fuel <b>{fuelPct}%</b>
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
                    {shownCrate.fragile ? ' · fragile' : ''}
                    {shownCrate.hazard === 'flammable' ? ' · flammable' : ''}
                    {shownCrate.hazard === 'liquid' ? ' · liquid' : ''} · pays $
                    {shownCrate.rate.toLocaleString('en-US')}
                    {phase === 'loading' && (
                      <span className="tg-panel-rest"> · {remaining} still on the dock</span>
                    )}
                  </p>
                  <p className="tg-panel-hint">
                    {phase === 'reloading'
                      ? 'Find it a spot on the deck. It keeps whatever the fall did to it.'
                      : shownCrate.hazard === 'flammable'
                        ? 'Pays well, and takes the truck with it if you break it. Low and braced.'
                        : shownCrate.hazard === 'liquid'
                          ? 'Burst this and it goes over the deck - nothing grips on a wet bed.'
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

        {(phase === 'arrived' || phase === 'stranded'
          || ((phase === 'failed' || phase === 'wrecked') && endingPlayed)) && (
          <div className="tg-overlay">
            <p className="tg-overlay-title">
              {phase === 'arrived' ? 'Delivered'
                : phase === 'wrecked' ? 'Rig totalled'
                  : phase === 'stranded' ? 'Out of fuel' : 'Load lost'}
            </p>
            <p className="tg-overlay-text">
              {phase === 'arrived'
                ? `$${payout.toLocaleString('en-US')} of $${route.maxPayout.toLocaleString('en-US')} arrived intact.`
                : phase === 'wrecked'
                  ? 'One impact too many. The load never got there, and neither did the truck.'
                  : phase === 'stranded'
                    ? 'Dry, short of the drop. Every second the engine runs costs fuel, and so does every trip back for something you dropped.'
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
          : 'Arrows or A/D to drive · Space to brake · watch the fuel · stop beside anything you drop and click it'}
      </p>
    </div>
  )
}
