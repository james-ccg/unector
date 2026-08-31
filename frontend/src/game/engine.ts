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
  /** Footprint as actually placed - swapped if the player laid it on its side. */
  w: number
  h: number
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
  /** Distance from the body's origin down to the road, for applying drive force. */
  contactDy: number
  /** Current throttle, eased toward what the player is asking for. */
  throttle: number
  /** Height of the deck surface right now, in world coordinates. */
  bedTop: () => number
  destroy: () => void
}

const TRUCK_START_X = 220
// Long enough to actually carry the load. At 190 the usable deck was 116px
// against 3-6 items totalling around 210px of width, so stacking two and
// three high was not a decision the player made - it was the only way to
// depart at all, and an unsecured three-high stack loses on any route.
// Measured over 24 seeds, that capped a careful load-out at 32% of the
// route's value. A deck that fits most loads in one layer makes stacking
// what it should be: a choice you take to fit a big load.
const CHASSIS_W = 250
const CHASSIS_H = 26
const WHEEL_R = 22
// Cargo sits ON this, not in it - the bed is an open flatbed on purpose.
const BED_H = 8

/**
 * The usable deck, as offsets from the chassis centre: the inner faces of
 * the rear lip and the headboard. Exported because the loading UI has to
 * clamp to exactly this - letting the player aim at a spot the physics will
 * immediately reject reads as the game ignoring the input.
 */
export const DECK_MIN_OFFSET = -120
export const DECK_MAX_OFFSET = 54

/** Where the wheels sit, measured from the chassis rectangle's centre. */
const REAR_AXLE = { x: -92, y: 30 }
const FRONT_AXLE = { x: 96, y: 30 }
/** Vertical distance from the chassis centre down to the contact line. */
const CONTACT_DY = REAR_AXLE.y + WHEEL_R

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
    TRUCK_START_X - 33, startY - CHASSIS_H / 2 - BED_H / 2, CHASSIS_W - 70, BED_H,
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
    TRUCK_START_X + DECK_MAX_OFFSET + 4, startY - CHASSIS_H / 2 - 19, 8, 30,
    { density: 0.002, friction: 1, label: 'bed' },
  )
  const rearLip = Matter.Bodies.rectangle(
    TRUCK_START_X + DECK_MIN_OFFSET - 4, startY - CHASSIS_H / 2 - 11, 8, 16,
    { density: 0.002, friction: 1, label: 'bed' },
  )

  /**
   * One rigid body, wheels included, rather than a chassis with wheels held
   * on by constraints.
   *
   * The constraint version never came to rest. Measured headlessly, a parked
   * empty truck moved 1.3px vertically every frame - up to 3.4px - forever,
   * and the camera turned that into the entire world shaking. Isolating it
   * ruled out everything else: a plain box on this terrain settles to
   * 0.00000px, a lone wheel settles to 0.00000px, chassis-plus-axles never
   * settles at all and after a few thousand frames diverges outright.
   *
   * Zero-length constraints are singular - Matter normalises the vector
   * between the two anchors to get the constraint direction, and at zero
   * separation that direction is numerical noise - but lengthening them did
   * not save it either: triangulating each wheel with two properly-lengthed
   * constraints still left 0.65-0.91px of jitter per frame at every
   * stiffness tried. The solver simply cannot hold this mass ratio steady.
   *
   * As one body it is exactly still. The cost is that the wheels no longer
   * spin as independent bodies, so the rig slides on round feet instead of
   * rolling, and it is driven by force at the contact line rather than by
   * torque on the wheels. Nothing the player can see depends on that
   * distinction; a picture that does not vibrate is something they cannot
   * help but see. Wheel rotation is drawn from distance travelled instead.
   */
  // Moderate friction, not the grip a rolling tyre would have: these feet
  // slide rather than roll, and at 0.95 the rig was a sled welded to the
  // road - it needed so much force to break away that once it did it shot
  // off at seventy pixels a frame. A speed cap in drive() governs the top
  // speed instead, which is both steadier and something a truck actually has.
  const wheelOptions: Matter.IBodyDefinition = {
    density: 0.008,
    friction: 0.25,
    frictionStatic: 0.4,
    restitution: 0.02,
    label: 'wheel',
  }
  const rearWheel = Matter.Bodies.circle(
    TRUCK_START_X + REAR_AXLE.x, startY + REAR_AXLE.y, WHEEL_R, wheelOptions,
  )
  const frontWheel = Matter.Bodies.circle(
    TRUCK_START_X + FRONT_AXLE.x, startY + FRONT_AXLE.y, WHEEL_R, wheelOptions,
  )

  const truckBody = Matter.Body.create({
    parts: [chassis, bed, headboard, rearLip, rearWheel, frontWheel],
    friction: 0.25,
    label: 'truck',
  })
  // Stands in for rolling resistance and engine braking: lifting off has to
  // slow the rig down, or every descent ends at terminal velocity.
  truckBody.frictionAir = 0.02

  bodies.push(truckBody)

  // ---- Finish line ---------------------------------------------------
  const finishX = (route.heights.length - 4) * SEGMENT_WIDTH

  Matter.Composite.add(world, bodies)

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

  const bedTopOffset = startY - CHASSIS_H / 2 - BED_H - truckBody.position.y

  return {
    engine,
    chassis: truckBody,
    rearWheel,
    frontWheel,
    cargo,
    finishX,
    contactDy: startY + CONTACT_DY - truckBody.position.y,
    throttle: 0,
    // Held as an offset from the body's own origin and evaluated live, so
    // the deck follows the rig as it pitches over the terrain instead of
    // being frozen at the height it happened to be built at. Matter puts a
    // compound body's origin at its centre of mass, which is nowhere near
    // the chassis rectangle's centre once the wheels are parts of it, so
    // the offset has to be measured rather than assumed.
    bedTop: () => truckBody.position.y + bedTopOffset,
    destroy: () => {
      Matter.Events.off(engine, 'collisionStart', onCollision)
      Matter.Composite.clear(world, false)
      Matter.Engine.clear(engine)
    },
  }
}

/**
 * Where an item would come to rest if it were set down at this offset.
 *
 * Shared with the loading UI rather than reimplemented there: the ghost the
 * player aims with has to be the same rectangle the physics will create, or
 * the preview is a lie in exactly the situation that matters most - a tight
 * stack where a few pixels decide whether it fits.
 */
export function planDrop(
  world: TruckWorld, crate: Crate, offsetX: number, rotated: boolean,
): { x: number; y: number; w: number; h: number } {
  const w = rotated ? crate.h : crate.w
  const h = rotated ? crate.w : crate.h
  const x = world.chassis.position.x + offsetX
  let y = world.bedTop() - h / 2 - 4

  for (const existing of world.cargo) {
    if (existing.lost) continue
    // Read the real bounds rather than the nominal footprint: an item that
    // settled at an angle occupies a taller box than it was dropped as, and
    // stacking onto its nominal height buries the new one inside it.
    const bounds = existing.body.bounds
    if (bounds.min.x < x + w / 2 - 4 && bounds.max.x > x - w / 2 + 4) {
      y = Math.min(y, bounds.min.y - h / 2 - 2)
    }
  }
  return { x, y, w, h }
}

/** Sets an item down on the bed at the given offset from the chassis centre.
 *
 * Stacks rather than overlaps: dropping two crates on the same spot used to
 * spawn them inside each other, and Matter resolves that by flinging both
 * apart at speed - which read as the game randomly destroying a load the
 * player had just placed correctly.
 *
 * `rotated` lays the item on its side. It matters most for a drum, which
 * stands on a footprint half its height and will go over on the first
 * camber - laying it down trades deck width for a load that stays put. */
export function loadCrate(
  world: TruckWorld, crate: Crate, offsetX: number, rotated = false,
): CargoBody {
  const { x, y, w, h } = planDrop(world, crate, offsetX, rotated)

  const body = Matter.Bodies.rectangle(x, y, w, h, {
    friction: 1.1,
    frictionStatic: 2.5,
    restitution: 0.02,
    label: 'cargo',
  })
  // Mass follows the real weight, not the footprint. Deriving it from a
  // density times an area meant a wide pallet outweighed a heavier drum
  // purely for being wide, so "heavy low and central" - the one piece of
  // advice the game gives - was not actually true of the physics.
  Matter.Body.setMass(body, crate.weight / 160)

  Matter.Composite.add(world.engine.world, body)
  // Placement is a crane setting it down, not a collision. Without this
  // grace period the drop onto the bed registered as an impact and charged
  // a fragile crate 12% damage before the truck had even moved.
  const entry: CargoBody = {
    body, crate, w, h, damage: 0, lost: false,
    settledAt: world.engine.timing.timestamp + 400,
  }
  world.cargo.push(entry)
  return entry
}

/** Throttle in [-1, 1]; negative reverses. */
/**
 * Drive force, brake force, and the speed the throttle stops pushing at.
 *
 * The cap and the force go together. Without a cap the rig sits wherever
 * friction happens to leave it, and that is a cliff rather than a curve:
 * measured across the real route, just under the break-away force it crawled
 * at 2.6px a frame, and just over it accelerated to 77px a frame. With the
 * cap the force only has to be enough to reach it, and the top speed is a
 * number rather than an accident. Gravity still carries it past the cap
 * downhill - which is where a load is most at risk, and so is exactly where
 * it should happen.
 */
const DRIVE_FORCE = 0.3
const BRAKE_FORCE = 0.34
const MAX_SPEED = 4.5

/**
 * How fast the throttle itself may move, per step.
 *
 * Applying the full force the instant a key goes down is dumping the clutch:
 * the deck accelerates out from under the load, and a crate was measured
 * sliding straight off the back within seconds of pulling away. Easing the
 * force in over about a third of a second is what a driver with a load on
 * actually does, and it makes the pedal something you can be gentle with.
 */
const THROTTLE_RATE = 0.05

/** Throttle in [-1, 1]; negative reverses. */
export function drive(world: TruckWorld, throttle: number) {
  const target = Math.max(-1, Math.min(1, throttle))
  const delta = target - world.throttle
  world.throttle += Math.max(-THROTTLE_RATE, Math.min(THROTTLE_RATE, delta))

  if (Math.abs(world.throttle) < 0.01) return
  if (Math.abs(world.chassis.velocity.x) >= MAX_SPEED
      && Math.sign(world.chassis.velocity.x) === Math.sign(world.throttle)) {
    return
  }
  applyAtRoad(world, world.throttle * DRIVE_FORCE)
}

/**
 * Slows the rig down.
 *
 * A force opposing travel rather than a multiplier on the velocity. The
 * multiplier version scaled the speed by 0.92 every step, which at sixty
 * steps a second is an emergency stop held down continuously - close to a
 * full g of deceleration, far more than friction can hold a crate against.
 * It made careful driving actively worse than flooring it, which is the
 * opposite of what this game is for. As a force it pitches the rig forward
 * the way braking should, so hauling up hard still threatens the load - it
 * just no longer guarantees losing it.
 */
export function brake(world: TruckWorld) {
  const vx = world.chassis.velocity.x
  if (Math.abs(vx) < 0.05) return
  // Let go of the throttle too - holding both would just fight itself.
  world.throttle *= 0.7
  applyAtRoad(world, -Math.sign(vx) * BRAKE_FORCE)
}

/**
 * Applies a horizontal force at the contact line rather than at the centre
 * of mass. A push down at road level is what makes a rig squat under power
 * and dive under braking, and that pitch is half of what shifts a badly
 * stacked load. Pushing through the centre of mass would move the truck
 * without ever disturbing what is on it.
 */
function applyAtRoad(world: TruckWorld, fx: number) {
  const body = world.chassis
  Matter.Body.applyForce(
    body,
    { x: body.position.x, y: body.position.y + world.contactDy },
    { x: fx, y: 0 },
  )
}

/** Marks cargo that has fallen off the truck or off the world. */
export function updateCargoState(world: TruckWorld) {
  for (const entry of world.cargo) {
    if (entry.lost) continue
    const dx = entry.body.position.x - world.chassis.position.x
    const dy = entry.body.position.y - world.chassis.position.y
    // Behind or below the truck by this much means it is on the road, not
    // on the bed, and there is no picking it back up.
    if (dy > 70 || Math.abs(dx) > CHASSIS_W) {
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
