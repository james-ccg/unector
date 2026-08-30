import Matter from 'matter-js'
import { BASE_GROUND_Y, SEGMENT_WIDTH, type Crate, type Route } from './route'

/**
 * The physics world: terrain, a truck that behaves like a truck, and cargo
 * that is held on by nothing but friction and how well it was stacked.
 *
 * The whole design point is that the load is NOT attached to the trailer.
 * Every other choice here follows from that - the bed has high friction, the
 * chassis is deliberately top-heavy when loaded badly, and damage comes from
 * real collision impulses rather than a scripted event. Driving carefully has
 * to be the thing that gets cargo through, or the game isn't about what it
 * claims to be about.
 */

export interface CargoBody {
  body: Matter.Body
  crate: Crate
  /** 0 = pristine, 1 = destroyed. Accumulated from impact impulses. */
  damage: number
  /** Left the trailer entirely - unrecoverable, pays nothing. */
  lost: boolean
  /** Engine timestamp until which impacts are ignored - see loadCrate. */
  settledAt: number
}

export interface TruckWorld {
  engine: Matter.Engine
  chassis: Matter.Body
  rearWheel: Matter.Body
  frontWheel: Matter.Body
  cargo: CargoBody[]
  /** World x the truck has to reach with its load. */
  finishX: number
  bedTop: number
  destroy: () => void
}

const TRUCK_START_X = 220
const CHASSIS_W = 190
const CHASSIS_H = 26
const WHEEL_R = 22
// Cargo sits ON this, not in it - the bed is an open flatbed on purpose.
const BED_H = 8

/**
 * Impact speed (px/step) below which a knock is just the road, not damage.
 *
 * Measured in relative velocity along the contact normal rather than
 * penetration depth: depth is a solver artefact that barely moves between a
 * gentle rest and a hard hit, so an earlier version keyed off it wrote off
 * every load within a second of it settling on the bed.
 */
// Above the speed a crate reaches just settling onto the bed - placing a
// load correctly has to cost nothing, or the player is punished for the
// one part of the game they got right.
const DAMAGE_SPEED = 3.6
const FRAGILE_SPEED = 2.4
/** How much of the excess speed turns into damage. */
// Steep, so the difference between a careful cruise and flooring it over a
// crest is visible in the payout rather than a rounding error.
const DAMAGE_SCALE = 0.14

export function createWorld(route: Route): TruckWorld {
  const engine = Matter.Engine.create()
  // A touch stronger than Matter's default: the default reads floaty for a
  // vehicle, and a load that drifts rather than falls doesn't teach anything.
  engine.gravity.y = 1.4

  const world = engine.world
  const bodies: Matter.Body[] = []

  // ---- Terrain -------------------------------------------------------
  // Each segment is its own angled slab. Matter has no heightfield, and a
  // single concave polygon would be decomposed unpredictably; slabs give
  // exact control over the surface the wheels actually touch.
  for (let i = 0; i < route.heights.length - 1; i++) {
    const x1 = i * SEGMENT_WIDTH
    const y1 = route.heights[i]
    const x2 = (i + 1) * SEGMENT_WIDTH
    const y2 = route.heights[i + 1]
    const midX = (x1 + x2) / 2
    const midY = (y1 + y2) / 2
    const length = Math.hypot(x2 - x1, y2 - y1)
    const angle = Math.atan2(y2 - y1, x2 - x1)

    const slab = Matter.Bodies.rectangle(midX, midY + 30, length, 60, {
      isStatic: true,
      angle,
      friction: 0.9,
      label: 'ground',
      render: { fillStyle: '#2a2a26' },
    })
    bodies.push(slab)
  }

  // ---- Truck ---------------------------------------------------------
  const startY = BASE_GROUND_Y - 70

  const chassis = Matter.Bodies.rectangle(TRUCK_START_X, startY, CHASSIS_W, CHASSIS_H, {
    // Heavy relative to the cargo, or a single crate would steer the truck.
    density: 0.006,
    friction: 0.6,
    label: 'chassis',
  })

  const bed = Matter.Bodies.rectangle(
    TRUCK_START_X - 30, startY - CHASSIS_H / 2 - BED_H / 2, CHASSIS_W - 60, BED_H,
    // High friction is what lets a well-stacked load ride; it is still not
    // enough to save a badly balanced one.
    { density: 0.002, friction: 1.4, frictionStatic: 3, label: 'bed' },
  )

  // A headboard at the front and a lip at the rear. Without them the bed is
  // a bare plate and the load slides off on the first incline no matter how
  // it was stacked or how gently it's driven - which made every run a loss
  // and took the player's decisions out of it entirely. Real flatbeds have
  // exactly these. Cargo can still tip over them, shift, or be shaken off;
  // it just isn't guaranteed to.
  const headboard = Matter.Bodies.rectangle(
    TRUCK_START_X + 32, startY - CHASSIS_H / 2 - 15, 8, 22,
    { density: 0.002, friction: 1, label: 'bed' },
  )
  const rearLip = Matter.Bodies.rectangle(
    TRUCK_START_X - 92, startY - CHASSIS_H / 2 - 11, 8, 16,
    { density: 0.002, friction: 1, label: 'bed' },
  )

  const truckBody = Matter.Body.create({
    parts: [chassis, bed, headboard, rearLip],
    friction: 0.8,
    label: 'truck',
  })

  const wheelOptions: Matter.IBodyDefinition = {
    density: 0.008,
    friction: 0.95,
    // Wheels need to shed energy or the truck pogos over every bump.
    frictionStatic: 2,
    restitution: 0.06,
    label: 'wheel',
  }
  const rearWheel = Matter.Bodies.circle(TRUCK_START_X - 62, startY + 30, WHEEL_R, wheelOptions)
  const frontWheel = Matter.Bodies.circle(TRUCK_START_X + 68, startY + 30, WHEEL_R, wheelOptions)

  // Stiff constraints rather than a spring: a flatbed rig has almost no give,
  // and suspension travel would soak up exactly the jolts the player is
  // supposed to be avoiding.
  const axleOptions = { stiffness: 0.9, damping: 0.2, length: 0 }
  const rearAxle = Matter.Constraint.create({
    bodyA: truckBody,
    pointA: { x: -62, y: 30 },
    bodyB: rearWheel,
    ...axleOptions,
  })
  const frontAxle = Matter.Constraint.create({
    bodyA: truckBody,
    pointA: { x: 68, y: 30 },
    bodyB: frontWheel,
    ...axleOptions,
  })

  bodies.push(truckBody, rearWheel, frontWheel)

  // ---- Finish line ---------------------------------------------------
  const finishX = (route.heights.length - 4) * SEGMENT_WIDTH

  Matter.Composite.add(world, [...bodies, rearAxle, frontAxle])

  const cargo: CargoBody[] = []

  // Damage is read off real collisions. Anything the cargo hits hard enough
  // counts - the ground, the chassis, another crate - so stacking badly is
  // punished by the same rule as driving badly.
  const onCollision = (event: Matter.IEventCollision<Matter.Engine>) => {
    for (const pair of event.pairs) {
      for (const entry of cargo) {
        if (pair.bodyA !== entry.body && pair.bodyB !== entry.body) continue
        const other = pair.bodyA === entry.body ? pair.bodyB : pair.bodyA

        // How fast the two were closing along the contact normal. A crate
        // riding the bed over a bump shares the truck's motion and scores
        // near zero here; one that has come off the deck and landed does not.
        const normal = pair.collision.normal
        const relX = entry.body.velocity.x - other.velocity.x
        const relY = entry.body.velocity.y - other.velocity.y
        const closingSpeed = Math.abs(relX * normal.x + relY * normal.y)

        if (engine.timing.timestamp < entry.settledAt) continue

        const threshold = entry.crate.fragile ? FRAGILE_SPEED : DAMAGE_SPEED
        if (closingSpeed > threshold) {
          entry.damage = Math.min(1, entry.damage + (closingSpeed - threshold) * DAMAGE_SCALE)
        }
      }
    }
  }
  // collisionStart only. Resting contact re-fires collisionActive every
  // single frame, so including it charged a stationary crate 60 impacts a
  // second and destroyed every load before the truck had moved.
  Matter.Events.on(engine, 'collisionStart', onCollision)

  return {
    engine,
    chassis: truckBody,
    rearWheel,
    frontWheel,
    cargo,
    finishX,
    bedTop: startY - CHASSIS_H / 2 - BED_H,
    destroy: () => {
      Matter.Events.off(engine, 'collisionStart', onCollision)
      Matter.Composite.clear(world, false)
      Matter.Engine.clear(engine)
    },
  }
}

/** Drops a crate onto the bed at the given offset from the chassis centre.
 *
 * Stacks rather than overlaps: dropping two crates on the same spot used to
 * spawn them inside each other, and Matter resolves that by flinging both
 * apart at speed - which read as the game randomly destroying a load the
 * player had just placed correctly. */
export function loadCrate(world: TruckWorld, crate: Crate, offsetX: number): CargoBody {
  const targetX = world.chassis.position.x + offsetX
  let dropY = world.bedTop - crate.size / 2 - 4

  for (const existing of world.cargo) {
    if (existing.lost) continue
    const halfWidths = (crate.size + existing.crate.size) / 2
    if (Math.abs(existing.body.position.x - targetX) < halfWidths - 4) {
      // Sit on top of whatever is already there.
      dropY = Math.min(dropY, existing.body.position.y - existing.crate.size / 2 - crate.size / 2)
    }
  }

  const body = Matter.Bodies.rectangle(
    targetX,
    dropY,
    crate.size,
    crate.size,
    {
      // Mass follows the real weight, so a heavy crate high up genuinely
      // does make the truck want to roll.
      density: crate.weight / 400000,
      friction: 1.1,
      frictionStatic: 2.5,
      restitution: 0.02,
      label: 'cargo',
    },
  )
  Matter.Composite.add(world.engine.world, body)
  // Placement is a crane setting it down, not a collision. Without this
  // grace period the drop onto the bed registered as an impact and charged
  // a fragile crate 12% damage before the truck had even moved.
  const entry: CargoBody = {
    body, crate, damage: 0, lost: false,
    settledAt: world.engine.timing.timestamp + 400,
  }
  world.cargo.push(entry)
  return entry
}

/** Throttle in [-1, 1]; negative reverses. */
export function drive(world: TruckWorld, throttle: number) {
  // Torque on the wheels rather than force on the chassis: it lets the
  // wheels lose traction on a climb, which is what makes terrain matter.
  //
  // Tuned against the actual body masses (wheel 12, truck 31.7): 0.32 moved
  // the rig 73px in three seconds on a 6400px route, which read as a broken
  // engine rather than a heavy load. Past about 8 it just spins the wheels
  // and covers LESS ground, so this sits below that.
  const torque = throttle * 3.4
  world.rearWheel.torque = torque
  world.frontWheel.torque = torque * 0.5
}

export function brake(world: TruckWorld) {
  for (const wheel of [world.rearWheel, world.frontWheel]) {
    Matter.Body.setAngularVelocity(wheel, wheel.angularVelocity * 0.82)
  }
  Matter.Body.setVelocity(world.chassis, {
    x: world.chassis.velocity.x * 0.94,
    y: world.chassis.velocity.y,
  })
}

/** Marks cargo that has fallen off the truck or off the world. */
export function updateCargoState(world: TruckWorld) {
  for (const entry of world.cargo) {
    if (entry.lost) continue
    const dx = entry.body.position.x - world.chassis.position.x
    const dy = entry.body.position.y - world.chassis.position.y
    // Behind or below the truck by this much means it is on the road, not
    // on the bed, and there is no picking it back up.
    if (dy > 60 || Math.abs(dx) > 190) {
      entry.lost = true
      entry.damage = 1
    }
  }
}

/** What the run is worth right now - damaged cargo pays proportionally. */
export function currentPayout(world: TruckWorld): number {
  return world.cargo.reduce(
    (sum, entry) => sum + Math.round(entry.crate.rate * (1 - entry.damage)),
    0,
  )
}
