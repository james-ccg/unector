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
 *
 * RIG DAMAGE: a run that is driven sensibly should finish with the truck
 * barely marked, and should never wreck. The threshold exists for genuine
 * slams - landing flat after clearing a crest, driving hard into a rise -
 * so if ordinary driving is registering damage here, it is set too low and
 * the player will be written off for nothing they did wrong.
 *
 * FUEL: the tank is what stops a careful run being free, so it has to be
 * tight without being unfair. A brisk run should finish with a comfortable
 * margin, a careful one with very little, and going back for something you
 * dropped should cost enough to be a real decision. If nothing ever runs
 * dry the tank is doing nothing; if the careful strategies run dry the game
 * has stopped being about looking after the load.
 */
import Matter from 'matter-js'
import { generateRoute, type Crate } from '../src/game/route.ts'
import {
  createWorld, loadCrate, reloadCargo, recoverableCargo, explodeTruck, drive, brake,
  coast, updateCargoState, currentPayout, DECK_MIN_OFFSET, DECK_MAX_OFFSET, MAX_SPEED,
  type TruckWorld,
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
    world.fuel = 1
    if (throttle) drive(world, throttle)
    coast(world)
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
  while (steps < 60 * 180 && world.chassis.position.x < world.finishX && world.fuel > 0) {
    // Hold the brake until properly back under speed, rather than pulsing it
    // at the threshold sixty times a second - which no person does, and
    // which shakes a load off on its own.
    if (strategy !== 'naive' && strategy !== 'tower') {
      if (world.chassis.velocity.x > cap) braking = true
      else if (world.chassis.velocity.x < cap * 0.75) braking = false
    }
    drive(world, braking ? 0 : 1)
    if (braking) brake(world)
    coast(world)
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
    steps++
    if (world.cargo.every((c) => c.state === 'gone')) break
  }

  const reached = world.chassis.position.x >= world.finishX
  const result = {
    pct: route.maxPayout ? (reached ? currentPayout(world) : 0) / route.maxPayout : 0,
    fuel: world.fuel,
    dry: world.fuel <= 0 && !reached,
    lost: world.cargo.filter((c) => c.state !== 'deck').length,
    truckDamage: world.truckDamage,
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
    `  rig ${(avg((r) => r.truckDamage) * 100).toFixed(0)}%/${(Math.max(...rs.map((r) => r.truckDamage)) * 100).toFixed(0)}%` +
    `  wrecked ${rs.filter((r) => r.truckDamage >= 1).length}` +
    `  fuel left ${(avg((r) => r.fuel) * 100).toFixed(0)}%` +
    ` (worst ${(Math.min(...rs.map((r) => r.fuel)) * 100).toFixed(0)}%)` +
    `  ran dry ${rs.filter((r) => r.dry).length}`,
  )
}

// ---- impacts ---------------------------------------------------------

/**
 * The distribution of ground impacts the rig actually takes.
 *
 * The damage threshold has to sit above what ordinary driving produces and
 * below what a genuine slam produces, and the only way to know where that is
 * is to look. Guessing put it at 6.5, where nothing in twenty-four routes
 * ever came close and the truck could not be wrecked at all.
 */
function impacts() {
  const speeds: number[] = []

  for (const seed of SEEDS) {
    const route = generateRoute(seed)
    const world = createWorld(route)
    for (const p of planLoad(route.crates, 'fullStack')) {
      loadCrate(world, p.crate, p.offset, p.laid)
    }

    Matter.Events.on(world.engine, 'collisionStart', (event) => {
      if (world.engine.timing.timestamp < 600) return
      for (const pair of event.pairs) {
        const aTruck = pair.bodyA.parent === world.chassis
        const bTruck = pair.bodyB.parent === world.chassis
        if (aTruck === bTruck) continue
        const other = aTruck ? pair.bodyB : pair.bodyA
        if (other.label !== 'ground') continue
        const n = pair.collision.normal
        speeds.push(Math.abs(
          world.chassis.velocity.x * n.x + world.chassis.velocity.y * n.y,
        ))
      }
    })

    for (let i = 0; i < 150; i++) Matter.Engine.update(world.engine, STEP)
    let steps = 0
    while (steps < 60 * 90 && world.chassis.position.x < world.finishX) {
      // Impacts are about the road, not the tank.
      world.fuel = 1
      drive(world, 1)
      coast(world)
      Matter.Engine.update(world.engine, STEP)
      updateCargoState(world)
      steps++
    }
    world.destroy()
  }

  speeds.sort((a, b) => a - b)
  const at = (q: number) => speeds[Math.min(speeds.length - 1, Math.floor(speeds.length * q))]
  console.log(`${speeds.length} ground impacts, flat out, over ${SEEDS.length} routes`)
  console.log(
    `  median ${at(0.5).toFixed(2)}   p90 ${at(0.9).toFixed(2)}` +
    `   p99 ${at(0.99).toFixed(2)}   worst ${(speeds.at(-1) ?? 0).toFixed(2)}`,
  )
}

// ---- recovery --------------------------------------------------------

/**
 * Drives a route badly on purpose, then goes back for what fell off.
 *
 * End to end, because the interesting failures are all at the seams: an item
 * that is unreachable however you park, one that goes back on and instantly
 * falls off again, or one that reloads but never counts toward the payout
 * because its state was not updated. None of those show up as a type error.
 */
function recovery() {
  let attempted = 0
  let collected = 0
  let stillOnAtTheEnd = 0
  let paidExtra = 0
  let fuelSpentRecovering = 0
  let strandedGoingBack = 0

  for (const seed of SEEDS) {
    const route = generateRoute(seed)
    const world = createWorld(route)
    // Deliberately bad: everything piled on one spot, so plenty comes off.
    for (const crate of route.crates) loadCrate(world, crate, clamp(-30, crate, false), false)
    for (let i = 0; i < 150; i++) {
      Matter.Engine.update(world.engine, STEP)
      updateCargoState(world)
    }

    let steps = 0
    let recovering = false
    let fuelAtFirstDrop = -1
    const beforeRecovery = new Set<number>()

    while (steps < 60 * 150 && world.chassis.position.x < world.finishX && world.fuel > 0) {
      const dropped = world.cargo.filter((c) => c.state === 'road')

      if (!recovering && dropped.length > 0) {
        recovering = true
        if (fuelAtFirstDrop < 0) fuelAtFirstDrop = world.fuel
        for (const d of dropped) beforeRecovery.add(world.cargo.indexOf(d))
      }

      if (recovering) {
        const reachable = recoverableCargo(world)
        if (reachable.length > 0) {
          attempted++
          // Rear of the deck, laid flat if that lowers it - the same advice
          // the game gives the player.
          const item = reachable[0]
          const laid = item.crate.h > item.crate.w
          const halfW = (laid ? item.crate.h : item.crate.w) / 2
          reloadCargo(world, item, DECK_MIN_OFFSET + halfW, laid)
          collected++
          recovering = world.cargo.some((c) => c.state === 'road')
        } else {
          // Back up toward it, then stop dead so the pickup can happen.
          const target = world.cargo.find((c) => c.state === 'road')
          if (!target) recovering = false
          else {
            const behind = target.body.position.x < world.chassis.position.x
            if (Math.abs(target.body.position.x - world.chassis.position.x) > 120) {
              drive(world, behind ? -1 : 1)
            } else {
              brake(world)
            }
          }
        }
      } else {
        // Back up to normal driving once everything is aboard again. An
        // earlier version crawled at 0.4 throttle for the whole rest of the
        // route after the first drop, which measured the cost of crawling
        // rather than the cost of the detour.
        const stillDown = world.cargo.some((c) => c.state === 'road')
        drive(world, stillDown ? 0.4 : 1)
        if (stillDown && world.chassis.velocity.x > 2) brake(world)
      }
      coast(world)

      Matter.Engine.update(world.engine, STEP)
      updateCargoState(world)
      steps++
    }

    if (fuelAtFirstDrop >= 0) fuelSpentRecovering += fuelAtFirstDrop - world.fuel
    if (world.fuel <= 0) strandedGoingBack++
    for (const idx of beforeRecovery) {
      const entry = world.cargo[idx]
      if (entry.state === 'deck') {
        stillOnAtTheEnd++
        paidExtra += Math.round(entry.crate.rate * (1 - entry.damage))
      }
    }
    world.destroy()
  }

  console.log(`${attempted} pickups attempted, ${collected} succeeded`)
  console.log(
    `${stillOnAtTheEnd} of them were still on the deck at the drop, ` +
    `worth $${paidExtra.toLocaleString('en-US')} that would otherwise have been left on the road`,
  )
  console.log(
    `the detours cost ${(fuelSpentRecovering / SEEDS.length * 100).toFixed(0)}% of a tank on average, ` +
    `and stranded the rig ${strandedGoingBack}/${SEEDS.length} times`,
  )
  if (collected === 0) console.log('  NOTHING COULD BE PICKED UP - the mechanic is dead')
}

// ---- wreck -----------------------------------------------------------

/**
 * The wreck is real bodies, not a drawing, so it can fail in ways a drawing
 * cannot: pieces that never come to rest, pieces flung to infinity, or a
 * NaN that quietly takes the whole engine down after the run is notionally
 * over. None of that is visible in a screenshot of the first frame.
 */
function wreck() {
  const route = generateRoute(1037)
  const world = createWorld(route)
  for (const p of planLoad(route.crates, 'fullStack')) loadCrate(world, p.crate, p.offset, p.laid)
  for (let i = 0; i < 150; i++) {
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
  }

  const carried = world.cargo.length
  explodeTruck(world)
  const pieces = world.debris.length

  // Twice over, to prove it is idempotent - the draw loop calls it from a
  // branch that runs every frame while the phase is 'wrecked'.
  explodeTruck(world)

  let peakSpeed = 0
  for (let i = 0; i < 60 * 4; i++) {
    Matter.Engine.update(world.engine, STEP)
    updateCargoState(world)
    for (const piece of world.debris) {
      peakSpeed = Math.max(peakSpeed, Math.hypot(piece.velocity.x, piece.velocity.y))
    }
  }

  const finite = world.debris.every(
    (b) => Number.isFinite(b.position.x) && Number.isFinite(b.position.y),
  )
  const settled = world.debris.filter(
    (b) => Math.hypot(b.velocity.x, b.velocity.y) < 0.6,
  ).length
  const nearby = world.debris.filter(
    (b) => Math.abs(b.position.x - world.chassis.position.x) < 900,
  ).length
  const thrown = world.cargo.filter((c) => c.state !== 'deck').length

  console.log(
    `${pieces} pieces (idempotent: ${world.debris.length === pieces ? 'yes' : 'NO'})` +
    `  peak ${peakSpeed.toFixed(1)}px/frame` +
    `  all finite: ${finite ? 'yes' : 'NO'}`,
  )
  console.log(
    `  after 4s: ${settled}/${pieces} come to rest, ${nearby}/${pieces} still on screen` +
    `, ${thrown}/${carried} of the load thrown clear`,
  )
  if (!finite || pieces === 0) console.log('  THE WRECK IS BROKEN')
  world.destroy()
}

// ---- hazards ---------------------------------------------------------

/**
 * Placarded freight, and what it does on the way out.
 *
 * None of this is visible from a screenshot: a drum that explodes and one
 * that does not look identical right up until the frame it matters, and the
 * deck going slippery has no appearance at all. So it is checked by doing
 * it - destroy one of each and look at what changed.
 */
function hazards() {
  let flammableTested = 0
  let liquidTested = 0
  let blastDamage = 0
  let gripLost = 0
  let shardsMade = 0

  for (const seed of SEEDS) {
    const route = generateRoute(seed)
    for (const kind of ['flammable', 'liquid'] as const) {
      const index = route.crates.findIndex((c) => c.hazard === kind)
      if (index < 0) continue

      const world = createWorld(route)
      const crate = route.crates[index]
      loadCrate(world, crate, -40, crate.h > crate.w)
      for (let i = 0; i < 120; i++) {
        Matter.Engine.update(world.engine, STEP)
        updateCargoState(world)
      }

      // The deck's grip lives on the compound parent, not on the bed part -
      // Matter reads friction off the parent for every contact a compound
      // body makes, so the part's own value is never consulted.
      const gripBefore = world.chassis.friction
      const damageBefore = world.truckDamage

      // Write it off outright and let updateCargoState notice.
      world.cargo[0].damage = 1
      updateCargoState(world)

      shardsMade += world.shards.length
      if (kind === 'flammable') {
        flammableTested++
        blastDamage += world.truckDamage - damageBefore
      } else {
        liquidTested++
        if (world.chassis.friction < gripBefore) gripLost++
      }
      world.destroy()
    }
  }

  console.log(
    `flammable: ${flammableTested} tested, average ${(blastDamage / Math.max(1, flammableTested) * 100).toFixed(0)}% of the rig taken off by the blast`,
  )
  console.log(
    `liquid: ${liquidTested} tested, the deck lost its grip in ${gripLost} of them`,
  )
  console.log(`every write-off left wreckage - ${shardsMade} pieces across ${flammableTested + liquidTested} of them`)
  if (flammableTested === 0 || liquidTested === 0) {
    console.log('  NO PLACARDED FREIGHT WAS GENERATED - the hazard code never runs')
  }
}

// ---- pulling away ----------------------------------------------------

/**
 * How the rig gets up to speed.
 *
 * It used to go from standing to full speed in about six tenths of a second,
 * which is what a hot hatch does. A loaded truck pulls hard from rest, runs
 * out of that gear, changes, and pulls again - so what this is looking for is
 * a curve that visibly steps rather than one smooth ramp, and a time to full
 * speed measured in seconds rather than fractions of one.
 */
function pullingAway() {
  for (const load of [false, true]) {
    // Flat ground on purpose. On the real road this measures the hills, not
    // the gearbox - it read as "the rig cannot get past 2.3" when the rig was
    // perfectly capable of 8.6 and simply had a washout in the way.
    const real = generateRoute(1037)
    const route = { ...real, heights: real.heights.map(() => real.heights[0]) }
    const world = createWorld(route)
    if (load) for (const p of planLoad(route.crates, 'fullStack')) loadCrate(world, p.crate, p.offset, p.laid)
    for (let i = 0; i < 200; i++) {
      Matter.Engine.update(world.engine, STEP)
      updateCargoState(world)
    }

    // Cruising speed is where the power fade balances the drag, which sits
    // below the cap by design - so time-to-speed is measured against that
    // rather than against a number the rig is never meant to reach.
    const cruise = MAX_SPEED * 0.87
    const samples: string[] = []
    let full = -1
    for (let i = 0; i < 60 * 8; i++) {
      drive(world, 1)
      coast(world)
      Matter.Engine.update(world.engine, STEP)
      updateCargoState(world)
      if (i % 30 === 29) samples.push(world.chassis.velocity.x.toFixed(1))
      if (full < 0 && world.chassis.velocity.x >= cruise) full = i
    }
    console.log(
      `${load ? 'loaded' : 'empty '} speed each half second: ${samples.slice(0, 10).join(' ')}` +
      `  ->  up to speed in ${full < 0 ? 'over 8s' : `${(full / 60).toFixed(1)}s`}`,
    )
    world.destroy()
  }
}

console.log('STILLNESS - a parked truck must not move at all\n')
stillness('parked, empty', false, 0)
stillness('parked, loaded', true, 0)
stillness('driving, loaded', true, 1)

console.log('\nBALANCE - loading well must beat loading badly, by a lot\n')
// Driving styles as a fraction of what the rig can do, not as bare speeds -
// those were picked when the top speed was 4.5 and quietly became "crawling"
// when it went up, which made the careful strategies look unplayable.
balance('one layer, gentle', 'oneLayer', MAX_SPEED * 0.5)
balance('full stack, gentle', 'fullStack', MAX_SPEED * 0.5)
balance('one layer, quick', 'oneLayer', MAX_SPEED * 0.72)
balance('full stack, quick', 'fullStack', MAX_SPEED * 0.72)
balance('thoughtless', 'naive', 99)
balance('all in one pile', 'tower', 99)

console.log('\nPULLING AWAY - a truck, not a hot hatch\n')
pullingAway()

console.log('\nIMPACTS - where the rig damage threshold has to sit\n')
impacts()

console.log('\nRECOVERY - going back for what you dropped\n')
recovery()

console.log('\nWRECK - the rig comes apart into real bodies\n')
wreck()

console.log('\nHAZARDS - what placarded freight does when it goes\n')
hazards()
