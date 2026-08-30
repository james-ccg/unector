import { useEffect, useRef, useState } from 'react'
import './TruckGame.css'

/** A small side-scrolling runner, in the tradition of Chrome's offline dino.
 *
 * Drawn on a canvas rather than assembled from DOM nodes or hand-written SVG
 * paths: it's a per-frame animation, which is what canvas is for, and it
 * keeps the whole thing to simple shape calls that stay legible.
 *
 * Colours are pulled from the app's CSS custom properties at start, so the
 * game inherits whichever theme the visitor is on instead of hard-coding a
 * palette that would be invisible in one of them. */

const WORLD = { w: 800, h: 260 }
const GROUND_Y = 210
const GRAVITY = 0.62
const JUMP_V = -12.4
const START_SPEED = 5.2
const MAX_SPEED = 12
const HIGH_SCORE_KEY = 'fp-truck-highscore'

type Phase = 'ready' | 'running' | 'over'

interface Obstacle {
  x: number
  w: number
  h: number
  kind: 'cone' | 'pallet' | 'barrel'
}

function readHighScore(): number {
  try {
    const raw = localStorage.getItem(HIGH_SCORE_KEY)
    const n = raw ? Number.parseInt(raw, 10) : 0
    return Number.isFinite(n) && n > 0 ? n : 0
  } catch {
    return 0
  }
}

function writeHighScore(score: number) {
  try {
    localStorage.setItem(HIGH_SCORE_KEY, String(score))
  } catch {
    // Private window or blocked storage - the run still counts, it just
    // won't be remembered.
  }
}

export default function TruckGame() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [phase, setPhase] = useState<Phase>('ready')
  const [score, setScore] = useState(0)
  const [highScore, setHighScore] = useState(readHighScore)

  // Everything the loop mutates lives in refs: React state re-renders, and a
  // 60fps loop must not.
  const state = useRef({
    y: GROUND_Y,
    vy: 0,
    speed: START_SPEED,
    distance: 0,
    obstacles: [] as Obstacle[],
    nextSpawn: 90,
    phase: 'ready' as Phase,
  })

  const jump = () => {
    const s = state.current
    if (s.phase === 'running') {
      // Only from the ground - no double-jumping out of trouble.
      if (s.y >= GROUND_Y) {
        s.vy = JUMP_V
      }
      return
    }
    // From "ready" or "over", the same input starts a fresh run.
    s.y = GROUND_Y
    s.vy = 0
    s.speed = START_SPEED
    s.distance = 0
    s.obstacles = []
    s.nextSpawn = 90
    s.phase = 'running'
    setScore(0)
    setPhase('running')
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const css = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback
    const COLORS = {
      ink: token('--text', '#f5f4f0'),
      muted: token('--hint', '#9b988f'),
      accent: token('--accent', '#c3f832'),
      border: token('--border', '#322f2a'),
      danger: token('--red', '#ff5c52'),
    }

    // Match the backing store to the device's pixel density, or the whole
    // scene renders soft on any modern display.
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      canvas.width = Math.round(rect.width * dpr)
      canvas.height = Math.round(rect.height * dpr)
    }
    resize()
    window.addEventListener('resize', resize)

    let raf = 0
    let lastTime = performance.now()

    const spawn = () => {
      const kinds: Obstacle['kind'][] = ['cone', 'pallet', 'barrel']
      const kind = kinds[Math.floor(Math.random() * kinds.length)]
      const size = kind === 'cone' ? { w: 20, h: 26 } : kind === 'barrel' ? { w: 24, h: 34 } : { w: 40, h: 22 }
      const s = state.current
      s.obstacles.push({ x: WORLD.w + 40, ...size, kind })
      // Gap is measured in world pixels, not frames, and scales WITH speed:
      // a jump lasts a fixed ~40 frames, so the faster the road moves the
      // more ground passes underneath before the truck lands. Sizing the gap
      // off airtime keeps every obstacle clearable at any speed.
      const airtimeFrames = (2 * Math.abs(JUMP_V)) / GRAVITY
      const minGap = airtimeFrames * s.speed + 90
      s.nextSpawn = minGap + Math.random() * 190
    }

    const drawTruck = (x: number, y: number) => {
      ctx.fillStyle = COLORS.accent
      // Trailer
      ctx.fillRect(x, y - 34, 46, 26)
      // Cab
      ctx.fillRect(x + 46, y - 26, 22, 18)
      ctx.fillRect(x + 46, y - 34, 14, 10)
      // Wheels
      ctx.fillStyle = COLORS.ink
      ctx.beginPath()
      ctx.arc(x + 12, y - 4, 6, 0, Math.PI * 2)
      ctx.arc(x + 36, y - 4, 6, 0, Math.PI * 2)
      ctx.arc(x + 60, y - 4, 6, 0, Math.PI * 2)
      ctx.fill()
    }

    const drawObstacle = (o: Obstacle) => {
      ctx.fillStyle = COLORS.danger
      const y = GROUND_Y - o.h
      if (o.kind === 'cone') {
        ctx.beginPath()
        ctx.moveTo(o.x + o.w / 2, y)
        ctx.lineTo(o.x + o.w, GROUND_Y)
        ctx.lineTo(o.x, GROUND_Y)
        ctx.closePath()
        ctx.fill()
      } else {
        ctx.fillRect(o.x, y, o.w, o.h)
        ctx.fillStyle = COLORS.border
        ctx.fillRect(o.x + 3, y + o.h / 2 - 2, o.w - 6, 4)
      }
    }

    const loop = (now: number) => {
      // Normalised to 60fps so the game runs at the same pace on a 144Hz
      // screen as on a 60Hz one.
      const dt = Math.min((now - lastTime) / (1000 / 60), 3)
      lastTime = now
      const s = state.current

      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      const scale = (rect.width * dpr) / WORLD.w
      ctx.setTransform(scale, 0, 0, scale, 0, 0)
      ctx.clearRect(0, 0, WORLD.w, WORLD.h)

      if (s.phase === 'running') {
        s.distance += s.speed * dt
        s.speed = Math.min(MAX_SPEED, START_SPEED + s.distance / 900)
        s.vy += GRAVITY * dt
        s.y = Math.min(GROUND_Y, s.y + s.vy * dt)

        // Counted down in the same world pixels the obstacles travel, so
        // the gap spawn() asked for is the gap that actually appears.
        s.nextSpawn -= s.speed * dt
        if (s.nextSpawn <= 0) spawn()

        for (const o of s.obstacles) o.x -= s.speed * dt
        s.obstacles = s.obstacles.filter((o) => o.x + o.w > -20)

        // Hitbox is inset from the drawing on purpose - a runner feels
        // unfair when the corners of the sprite count.
        const tx = 60 + 6
        const tw = 68 - 12
        const ty = s.y - 34 + 4
        const th = 30
        for (const o of s.obstacles) {
          const oy = GROUND_Y - o.h
          if (tx < o.x + o.w && tx + tw > o.x && ty < oy + o.h && ty + th > oy) {
            s.phase = 'over'
            setPhase('over')
            const final = Math.floor(s.distance / 12)
            setScore(final)
            setHighScore((prev) => {
              if (final > prev) {
                writeHighScore(final)
                return final
              }
              return prev
            })
            break
          }
        }
        if (s.phase === 'running') setScore(Math.floor(s.distance / 12))
      }

      // Ground
      ctx.strokeStyle = COLORS.border
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(0, GROUND_Y)
      ctx.lineTo(WORLD.w, GROUND_Y)
      ctx.stroke()

      // Dashes, offset by distance so the road reads as moving
      ctx.strokeStyle = COLORS.muted
      ctx.lineWidth = 2
      ctx.setLineDash([14, 22])
      ctx.lineDashOffset = s.distance % 36
      ctx.beginPath()
      ctx.moveTo(0, GROUND_Y + 14)
      ctx.lineTo(WORLD.w, GROUND_Y + 14)
      ctx.stroke()
      ctx.setLineDash([])

      for (const o of s.obstacles) drawObstacle(o)
      drawTruck(60, s.y)

      raf = requestAnimationFrame(loop)
    }

    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [])

  // Space and ArrowUp are the conventional controls; both are swallowed so
  // the page doesn't scroll out from under the game.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' || e.code === 'ArrowUp') {
        e.preventDefault()
        jump()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="truck-game">
      <div className="truck-game-hud">
        <span className="truck-game-score">
          Score <b>{String(score).padStart(5, '0')}</b>
        </span>
        {highScore > 0 && (
          <span className="truck-game-score is-best">
            Best <b>{String(highScore).padStart(5, '0')}</b>
          </span>
        )}
      </div>

      <div className="truck-game-stage">
        <canvas
          ref={canvasRef}
          className="truck-game-canvas"
          role="img"
          aria-label="A truck running along a road, jumping obstacles"
        />
        {phase !== 'running' && (
          <div className="truck-game-overlay">
            <p className="truck-game-overlay-title">
              {phase === 'ready' ? 'Ready to roll' : 'You hit something'}
            </p>
            <p className="truck-game-overlay-text">
              {phase === 'ready'
                ? 'Jump the obstacles. Press Space, or tap the button below.'
                : `You made it ${score} before the crash.`}
            </p>
          </div>
        )}
      </div>

      {/* A real button, not just the keyboard handler: this has to work on a
          phone, and it gives the control a focusable, labelled target. */}
      <button type="button" className="btn btn-primary truck-game-button" onClick={jump}>
        {phase === 'running' ? 'Jump' : phase === 'over' ? 'Drive again' : 'Start driving'}
      </button>
      <p className="truck-game-hint">Space or ↑ to jump</p>
    </div>
  )
}
