/**
 * Runs the game's real physics headlessly and prints what it measures.
 *
 * This exists because the two things that decide whether the game is any
 * good are both invisible to every other check we have. Types, lint and the
 * build all passed while a parked truck vibrated 1.3px every frame - which
 * on screen was the entire world shaking - and they would equally have
 * passed with a load that could never be delivered. Watching it in a browser
 * catches the first only if you happen to look closely, and the second not
 * at all, because you cannot eyeball an average over two dozen routes.
 *
 * Run it after touching engine.ts or route.ts:
 *
 *   npm run physics
 *
 * Two things to look at.
 *
 * STILLNESS: a parked truck must read 0.000. Anything above that is the
 * camera's input jittering, and the camera is glued to the chassis, so it
 * comes out as the whole scene shaking. If this regresses, bisect it the way
 * it was found the first time - a plain box on this terrain settles to
 * 0.000, a lone wheel settles to 0.000, so anything that does not settle is
 * in how the truck is assembled rather than in the world around it.
 *
 * BALANCE: the strategies must stay in order. Loading well has to beat
 * loading badly by a wide margin, or the game is not about what it claims to
 * be about. Taking a full stack and taking only what fits in one layer
 * should pay about the same - that is the decision the Depart button offers,
 * and it stops being a decision if one side dominates.
 */
import Matter from 'matter-js'
import { generateRoute, type Crate } from '../src/game/route.ts'
import {
  createWorld, loadCrate, drive, brake, updateCargoState, currentPayout,
  DECK_MIN_OFFSET, DECK_MAX_OFFSET, type TruckWorld,
} from '../src/game/engine.ts'

const SEEDS = Array.from({ length: 24 }, (_, i) => 1000 + i * 37)
const STEP = 1000 / 60

// ---- stillness -------------------------------------------------------

function stillness(label: string, load: boolean, throttle: number) {
  const route = generateRoute(1037)
  const world = createWorld(route)
  if (load) {
    let cursor = DECK_MIN_OFFSET
    for (const crate of route.crates) {
      loadCrate(world, crate, cursor + crate.w / 2, false)
      cursor += crate.w
    }
  }
  for (let i = 0; i < 180; i++) {
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
  }

  let prev = world.chassis.position.y
  let sum = 0
  let max = 0
  for (let i = 0; i < 600; i++) {
    if (throttle) drive(world, throttle)
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
    const d = Math.abs(world.chassis.position.y - prev)
    prev = world.chassis.position.y
    sum += d
    max = Math.max(max, d)
  }
  const mean = sum / 600
  const verdict = throttle ? '' : mean < 0.005 ? '  STILL' : '  SHAKING - see the note above'
  console.log(
    `${label.padEnd(18)} dy/frame mean ${mean.toFixed(4).padStart(8)}  max ${max.toFixed(3).padStart(7)}${verdict}`,
  )
  world.destroy()
}

// ---- balance ---------------------------------------------------------

type Strategy = 'oneLayer' | 'fullStack' | 'naive' | 'tower'

function clamp(offset: number, crate: Crate, laid: boolean) {
  const halfW = (laid ? crate.h : crate.w) / 2
  return Math.max(DECK_MIN_OFFSET + halfW, Math.min(DECK_MAX_OFFSET - halfW, offset))
}

function planLoad(crates: Crate[], strategy: Strategy) {
  const out: { crate: Crate; offset: number; laid: boolean }[] = []

  if (strategy === 'tower') {
    for (const crate of crates) out.push({ crate, offset: clamp(-30, crate, false), laid: false })
    return out
  }

  if (strategy === 'naive') {
    let cursor = DECK_MIN_OFFSET
    for (const crate of crates) {
      out.push({ crate, offset: clamp(cursor + crate.w / 2, crate, false), laid: false })
      cursor += crate.w
    }
    return out
  }

  // Heaviest first, laid flat when that lowers it, packed from the rear lip
  // forward. Either stop when the row is full, or start a second one.
  const order = [...crates].sort((a, b) => b.weight - a.weight)
  let cursor = DECK_MIN_OFFSET
  let row = 0
  for (const crate of order) {
    const laid = crate.h > crate.w
    const w = laid ? crate.h : crate.w
    if (cursor + w > DECK_MAX_OFFSET) {
      if (strategy === 'oneLayer') continue
      row++
      cursor = DECK_MIN_OFFSET + row * 20
    }
    out.push({ crate, offset: clamp(cursor + w / 2, crate, laid), laid })
    cursor += w
  }
  return out
}

function run(seed: number, strategy: Strategy, cap: number) {
  const route = generateRoute(seed)
  const world: TruckWorld = createWorld(route)
  let offDeck = 0
  for (const p of planLoad(route.crates, strategy)) {
    const halfW = (p.laid ? p.crate.h : p.crate.w) / 2
    if (p.offset - halfW < DECK_MIN_OFFSET - 0.5 || p.offset + halfW > DECK_MAX_OFFSET + 0.5) offDeck++
    loadCrate(world, p.crate, p.offset, p.laid)
  }
  for (let i = 0; i < 150; i++) {
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
  }

  let steps = 0
  let braking = false
  while (steps < 60 * 180 && world.chassis.position.x < world.finishX) {
    // Hold the brake until properly back under speed, rather than pulsing it
    // at the threshold sixty times a second - which no person does, and
    // which shakes a load off on its own.
    if (strategy !== 'naive' && strategy !== 'tower') {
      if (world.chassis.velocity.x > cap) braking = true
      else if (world.chassis.velocity.x < cap * 0.75) braking = false
    }
    drive(world, braking ? 0 : 1)
    if (braking) brake(world)
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
    steps++
    if (world.cargo.every((c) => c.lost)) break
  }

  const reached = world.chassis.position.x >= world.finishX
  const result = {
    pct: route.maxPayout ? (reached ? currentPayout(world) : 0) / route.maxPayout : 0,
    lost: world.cargo.filter((c) => c.lost).length,
    carried: world.cargo.length,
    seconds: steps / 60,
    reached,
    offDeck,
  }
  world.destroy()
  return result
}

function balance(label: string, strategy: Strategy, cap: number) {
  const rs = SEEDS.map((s) => run(s, strategy, cap))
  const avg = (f: (r: typeof rs[0]) => number) => rs.reduce((a, r) => a + f(r), 0) / rs.length
  console.log(
    `${label.padEnd(22)} paid ${(avg((r) => r.pct) * 100).toFixed(0).padStart(3)}% of max` +
    `  carried ${avg((r) => r.carried).toFixed(1)}  lost ${avg((r) => r.lost).toFixed(1)}` +
    `  arrived ${String(rs.filter((r) => r.reached).length).padStart(2)}/${rs.length}` +
    `  ${avg((r) => r.seconds).toFixed(0)}s` +
    `  off-deck ${rs.reduce((a, r) => a + r.offDeck, 0)}`,
  )
}

console.log('STILLNESS - a parked truck must not move at all\n')
stillness('parked, empty', false, 0)
stillness('parked, loaded', true, 0)
stillness('driving, loaded', true, 1)

console.log('\nBALANCE - loading well must beat loading badly, by a lot\n')
balance('one layer, gentle', 'oneLayer', 2.25)
balance('full stack, gentle', 'fullStack', 2.25)
balance('one layer, quick', 'oneLayer', 3)
balance('full stack, quick', 'fullStack', 3)
balance('thoughtless', 'naive', 99)
balance('all in one pile', 'tower', 99)
