import { useCallback, useEffect, useRef, useState } from 'react'
import Matter from 'matter-js'
import { generateRoute, SEGMENT_WIDTH, type Route } from './route'
import {
  createWorld, loadCrate, drive, brake, updateCargoState, currentPayout,
  type TruckWorld,
} from './engine'
import './TruckGame.css'

/**
 * Haul a load from A to B without wrecking it.
 *
 * Two phases. First you decide how to stack the crates - heavy low and
 * central, or take the risk of piling them. Then you drive, and the only
 * thing holding the load on is how well you stacked it and how gently you
 * drive. Speed is not scored; what arrives intact is.
 */

type Phase = 'loading' | 'driving' | 'arrived' | 'failed'

const VIEW = { w: 900, h: 520 }

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

  const [route, setRoute] = useState<Route>(() => generateRoute(seed ?? (Math.random() * 2 ** 31) | 0))
  const [phase, setPhase] = useState<Phase>('loading')
  const [placed, setPlaced] = useState(0)
  const [payout, setPayout] = useState(0)
  const [progress, setProgress] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // ---- world lifecycle ------------------------------------------------
  useEffect(() => {
    const world = createWorld(route)
    worldRef.current = world
    return () => {
      world.destroy()
      worldRef.current = null
    }
  }, [route])

  const startOver = useCallback((nextSeed?: number) => {
    setRoute(generateRoute(nextSeed ?? (Math.random() * 2 ** 31) | 0))
    setPhase('loading')
    setPlaced(0)
    setPayout(0)
    setProgress(0)
  }, [])

  // ---- loading: drop the next crate at a chosen offset -----------------
  const placeCrate = (offsetX: number) => {
    const world = worldRef.current
    if (!world || phase !== 'loading' || placed >= route.crates.length) return
    loadCrate(world, route.crates[placed], offsetX)
    setPlaced((n) => n + 1)
  }

  const depart = () => {
    if (placed === 0) return
    setPhase('driving')
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
      if (phase === 'driving' || phase === 'loading') {
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
      // is what the player is actually looking at.
      const camX = Math.max(0, world.chassis.position.x - VIEW.w * 0.35)
      const camY = Math.max(0, world.chassis.position.y - VIEW.h * 0.55)
      ctx.save()
      ctx.translate(-camX, -camY)

      // Terrain
      ctx.fillStyle = COLORS.ground
      ctx.beginPath()
      ctx.moveTo(0, VIEW.h + camY + 400)
      for (let i = 0; i < route.heights.length; i++) {
        ctx.lineTo(i * SEGMENT_WIDTH, route.heights[i])
      }
      ctx.lineTo((route.heights.length - 1) * SEGMENT_WIDTH, VIEW.h + camY + 400)
      ctx.closePath()
      ctx.fill()

      // Finish marker
      ctx.strokeStyle = COLORS.accent
      ctx.lineWidth = 3
      ctx.setLineDash([10, 8])
      ctx.beginPath()
      ctx.moveTo(world.finishX, 0)
      ctx.lineTo(world.finishX, VIEW.h + camY + 400)
      ctx.stroke()
      ctx.setLineDash([])

      // Truck
      const drawBody = (body: Matter.Body, fill: string) => {
        ctx.fillStyle = fill
        ctx.beginPath()
        const verts = body.vertices
        ctx.moveTo(verts[0].x, verts[0].y)
        for (let i = 1; i < verts.length; i++) ctx.lineTo(verts[i].x, verts[i].y)
        ctx.closePath()
        ctx.fill()
      }
      for (const part of world.chassis.parts.slice(1)) drawBody(part, COLORS.accent)
      for (const wheel of [world.rearWheel, world.frontWheel]) {
        ctx.fillStyle = COLORS.ink
        ctx.beginPath()
        ctx.arc(wheel.position.x, wheel.position.y, wheel.circleRadius || 20, 0, Math.PI * 2)
        ctx.fill()
      }

      // Cargo, tinted by how battered it is - the player needs to see damage
      // accumulating, not just find out at the end.
      for (const entry of world.cargo) {
        const hue = entry.damage > 0.6 ? COLORS.danger : entry.damage > 0.2 ? COLORS.amber : COLORS.muted
        drawBody(entry.body, hue)
      }

      ctx.restore()

      if (phase === 'driving') {
        const reached = world.chassis.position.x >= world.finishX
        const allGone = world.cargo.every((c) => c.lost)
        setProgress(Math.min(1, world.chassis.position.x / world.finishX))
        setPayout(currentPayout(world))
        if (reached || allGone) {
          const delivered = world.cargo.filter((c) => !c.lost && c.damage < 0.999).length
          const lost = world.cargo.filter((c) => c.lost).length
          const final = reached ? currentPayout(world) : 0
          setPhase(reached ? 'arrived' : 'failed')
          setPayout(final)
          onFinish?.({ payout: final, delivered, lost })
        }
      }

      raf = requestAnimationFrame(frame)
    }

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [route, phase, onFinish])

  // ---- keyboard --------------------------------------------------------
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === 'ArrowRight' || e.code === 'KeyD') inputRef.current.throttle = 1
      if (e.code === 'ArrowLeft' || e.code === 'KeyA') inputRef.current.throttle = -1
      if (e.code === 'Space') {
        e.preventDefault()
        inputRef.current.braking = true
      }
    }
    const up = (e: KeyboardEvent) => {
      if (['ArrowRight', 'KeyD', 'ArrowLeft', 'KeyA'].includes(e.code)) inputRef.current.throttle = 0
      if (e.code === 'Space') inputRef.current.braking = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

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

  return (
    <div className="tg" ref={shellRef}>
      <div className="tg-hud">
        <span className="tg-stat">Load <b>{placed}/{route.crates.length}</b></span>
        <span className="tg-stat">Value <b>${payout.toLocaleString('en-US')}</b></span>
        <span className="tg-stat is-muted">Max <b>${route.maxPayout.toLocaleString('en-US')}</b></span>
        <button type="button" className="tg-icon-btn" onClick={toggleFullscreen}>
          {isFullscreen ? 'Exit full screen' : 'Full screen'}
        </button>
      </div>

      <div className="tg-stage">
        <canvas ref={canvasRef} className="tg-canvas" />

        {phase === 'driving' && (
          <div className="tg-progress" aria-hidden="true">
            <span style={{ width: `${progress * 100}%` }} />
          </div>
        )}

        {phase === 'loading' && (
          <div className="tg-overlay tg-overlay-loading">
            <p className="tg-overlay-title">Load the trailer</p>
            {nextCrate ? (
              <p className="tg-overlay-text">
                Next: {nextCrate.weight}kg{nextCrate.fragile ? ' · fragile' : ''} · pays $
                {nextCrate.rate.toLocaleString('en-US')}. Heavy and low rides best.
              </p>
            ) : (
              <p className="tg-overlay-text">Trailer loaded. Drive carefully.</p>
            )}
            <div className="tg-place-row">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => placeCrate(-55)} disabled={!nextCrate}>
                Rear
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => placeCrate(-20)} disabled={!nextCrate}>
                Centre
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => placeCrate(15)} disabled={!nextCrate}>
                Front
              </button>
            </div>
            <button type="button" className="btn btn-primary" onClick={depart} disabled={placed === 0}>
              {remaining > 0 ? `Depart with ${placed} of ${route.crates.length}` : 'Depart'}
            </button>
          </div>
        )}

        {(phase === 'arrived' || phase === 'failed') && (
          <div className="tg-overlay">
            <p className="tg-overlay-title">
              {phase === 'arrived' ? 'Delivered' : 'Load lost'}
            </p>
            <p className="tg-overlay-text">
              {phase === 'arrived'
                ? `$${payout.toLocaleString('en-US')} of $${route.maxPayout.toLocaleString('en-US')} arrived intact.`
                : 'Everything came off the trailer before the drop.'}
            </p>
            <button type="button" className="btn btn-primary" onClick={() => startOver()}>
              New route
            </button>
          </div>
        )}
      </div>

      {/* Held buttons, so touch devices get the same continuous throttle a
          held key gives - a tap-per-press control would make the hills
          unplayable on a phone. */}
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
      <p className="tg-hint">Arrow keys or A/D to drive · Space to brake</p>
    </div>
  )
}
