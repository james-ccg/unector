import Matter from 'matter-js'
import { BASE_GROUND_Y, SEGMENT_WIDTH, type Crate, type CrateKind, type Route } from './route'

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

/**
 * Where an item is.
 *
 * Coming off the deck used to be the end of it - the item was written off on
 * the spot and paid nothing. It is now a setback rather than a verdict: it
 * is lying on the road, it keeps whatever damage the fall did to it, and a
 * driver who stops and goes back can put it on again. Only what is actually
 * on the deck at the drop gets paid, so leaving it there still costs the
 * whole item; the player just gets to decide whether it is worth the detour.
 */
export type CargoState = 'deck' | 'road' | 'gone'

/** A fragment of freight that has come apart. */
export interface Shard {
  body: Matter.Body
  kind: CrateKind
}

export interface WorldEvent {
  kind: 'shatter' | 'blast' | 'spill'
  x: number
  y: number
}

export interface CargoBody {
  body: Matter.Body
  crate: Crate
  /** Footprint as actually placed - swapped if the player laid it on its side. */
  w: number
  h: number
  /** 0 = pristine, 1 = destroyed. Accumulated from impact impulses. */
  damage: number
  state: CargoState
  /**
   * Mass before anything soaked into it.
   *
   * Traction is worked out from this rather than from the body's current
   * mass, so water taken on is pure burden: it makes the rig heavier to move
   * without giving the tyres anything extra to hold with. That is the whole
   * point of the effect - a wet load should pull away like a wet load.
   */
  dryMass: number
  /** Engine timestamp the load dries out at, or 0 if it is not wet. */
  wetUntil: number
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
  /** 0 = straight off the lot, 1 = wrecked. Accumulated from real impacts. */
  truckDamage: number
  /** True while the throttle is asking for more than the tyres can give. */
  slipping: boolean
  /** Set by brake(); the caller clears it once it has drawn the skid. */
  braking: boolean
  /** What is left of the rig once it has been written off. */
  debris: Matter.Body[]
  /** Wreckage of freight that has been destroyed outright. */
  shards: Shard[]
  /**
   * Things that just happened and want drawing once. The renderer drains
   * this every frame - the engine has no clock of its own worth trusting for
   * animation, and the alternative is the physics knowing about timing.
   */
  events: WorldEvent[]
  /** Engine timestamp the deck dries out at, or 0 if it is dry. */
  deckSoakedUntil: number
  /** What is left in the tank, 1 to 0. Only burns while under way. */
  fuel: number
  /** Engine timestamp until which impacts on the rig are ignored. */
  truckSettledAt: number
  /** Height of the deck surface right now, in world coordinates. */
  bedTop: () => number
  /**
   * Where the chassis rectangle's centre sits relative to the body origin.
   *
   * Matter puts a compound body's origin at its centre of mass, which is
   * nowhere near the middle of the chassis once the wheels are part of it.
   * Anything drawn in chassis coordinates has to go through this.
   */
  hullOffset: { x: number; y: number }
  /** The deck surface in the same frame, for working out what is on it. */
  deckLocalY: number
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
 * How far the road runs beyond the route at each end.
 *
 * Because there is a building at the start and a yard at the finish, and a
 * player who reverses out of the dock to see what is behind them should find
 * ground there rather than fall off the edge of the world.
 */
const RUNOFF = 900
/**
 * Rolling resistance at the road surface.
 *
 * Effectively zero, because the rig slides on its wheels rather than rolling
 * them - any contact friction here is a lie about rolling. Everything the
 * tyres are meant to do (pull, stop, hold on a slope) is an explicit force
 * in drive(), brake() and coast() instead.
 *
 * The exact value matters far more than it looks. Measured under a constant
 * half-g of tractive effort on flat ground, 0.03 caps the rig at 2.6px a
 * frame and 0.002 lets it reach 8.6. Anything that feels like a reasonable
 * small number here is not small enough.
 */
const GROUND_FRICTION = 0.002
/** Drag on freight lying in the road - see updateCargoState. */
const ROAD_DRAG = 0.08

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
const DAMAGE_SPEED = 5.6
const FRAGILE_SPEED = 3.7
/**
 * The rig is far tougher than what it carries, but not indestructible.
 *
 * Both numbers come from measurement rather than taste. Over 5000 ground
 * impacts, driven flat out across two dozen routes, the median contact is
 * 0.99 and the 99th percentile is 2.82 - so a threshold of 3.2 means
 * ordinary driving, however brisk, never marks the truck at all. Only
 * landing off a washout reaches past it, at 4.5-5, and at this scale three
 * or four of those finish the rig.
 *
 * The first guess here was 6.5, which nothing in any route ever reached:
 * the damage existed but could not happen. Worth remembering that the top
 * of the range is set by the speed cap, so lowering that lowers this too.
 */
const TRUCK_DAMAGE_SPEED = 4.4
const TRUCK_DAMAGE_SCALE = 0.15

/** How much of the excess speed turns into damage. */
// Steep, so the difference between a careful cruise and flooring it over a
// crest is visible in the payout rather than a rounding error.
const DAMAGE_SCALE = 0.14

/**
 * The most a single impact can take off an item.
 *
 * Without this, one bad landing wrote a crate off outright, and going back
 * for something you dropped was pointless - measured over two dozen routes,
 * every item recovered off the road was already worth exactly nothing by the
 * time it was picked up. Capped, a fall costs about a third of the item, so
 * the first one is well worth going back for, the second is a judgement
 * call, and by the third there is nothing left to save. That is a curve
 * rather than a cliff, and the player can see where they are on it from the
 * colour of the crate.
 */
const MAX_DAMAGE_PER_IMPACT = 0.35

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

    // Butted end to end, not overlapped. Overlapping them was an attempt at
    // stopping the wheels catching on the seams, which turned out not to be
    // a problem at all - and the doubled contacts at every join pushed a
    // parked empty rig around at 0.03px a frame, which is the one thing the
    // ground must never do.
    const slab = Matter.Bodies.rectangle(midX, midY + 30, length, 60, {
      isStatic: true,
      angle,
      // The road is the frictionless half of the contact, not the wheels.
      //
      // Matter reads friction off the PARENT of a compound body, never off
      // the part - pair.friction is min(parentA, parentB) and
      // pair.frictionStatic is max(parentA, parentB). So setting the wheels
      // to 0.002 bought nothing at all: the rig parent's own values decided
      // every contact it made. It also meant the deck's carefully-set grip
      // of 1.4 had never once been used - the load was riding on whatever
      // the parent said, which is the same 0.002 the wheels had.
      //
      // Since one number has to serve every contact the rig makes, the rig
      // keeps the high one, for the load, and the road carries the low one,
      // for the wheels.
      friction: 0.002,
      // Zero, and this matters more than it looks.
      //
      // Matter takes the MINIMUM of the two bodies' `friction` for a contact
      // but the MAXIMUM of their `frictionStatic`. So the wheels being
      // frictionless bought nothing: the road's default static friction of
      // 0.5 won every contact and quietly held the rig. It is what put a
      // break-away cliff in the old contact-driven drive model, and with the
      // gentler tractive force of a geared engine it stopped the truck
      // getting past 1px a frame at all - measured with drag and rolling
      // resistance both switched off, so there was nothing else left to
      // blame. Cargo that falls off still comes to rest, on kinetic friction.
      frictionStatic: 0,
      label: 'ground',
      render: { fillStyle: '#2a2a26' },
    })
    // Assigned AFTER construction, and that is the whole point.
    //
    // Passing isStatic in the options makes Matter run Body.setStatic, which
    // sets friction = 1 unconditionally - so every friction value ever given
    // to these slabs in the constructor was thrown away, and the wheels have
    // been sliding on friction 1.0 the entire time. That is what put a
    // break-away cliff in the drive model, what made lowering the wheels'
    // own friction achieve nothing, and what left the rig unable to get past
    // 2.6px a frame under a force that reaches 25 in open space.
    slab.friction = GROUND_FRICTION
    slab.frictionStatic = 0
    bodies.push(slab)
  }

  // Apron at each end, so the yard and the dock stand on something. Without
  // these the world simply stops at the first and last sample, and reversing
  // away from the loading dock drops the rig into nothing.
  for (const [from, to, height] of [
    [-RUNOFF, 0, route.heights[0]],
    [
      (route.heights.length - 1) * SEGMENT_WIDTH,
      (route.heights.length - 1) * SEGMENT_WIDTH + RUNOFF,
      route.heights[route.heights.length - 1],
    ],
  ] as [number, number, number][]) {
    const apron = Matter.Bodies.rectangle(
      (from + to) / 2, height + 30, to - from, 60,
      { isStatic: true, label: 'ground', render: { fillStyle: '#2a2a26' } },
    )
    apron.friction = GROUND_FRICTION
    apron.frictionStatic = 0
    bodies.push(apron)
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
  // Effectively frictionless, and deliberately so.
  //
  // These feet slide where a real wheel would roll, so any contact friction
  // here is a lie about rolling - and worse, it is a lie with a cliff in it.
  // Measured on flat ground, contact friction gave the rig a break-away
  // point: below it the throttle could not push past 2.6px a frame however
  // hard it pushed, and just above it the rig tore loose and reached 27 while
  // spinning through thousands of degrees. There is no usable range between
  // those, which is what made the acceleration feel wrong - the pedal barely
  // connected to the speed.
  //
  // Everything the tyres are supposed to do - pull, stop, resist rolling,
  // hold on a slope - is now an explicit force in drive(), brake() and
  // coast(), where it is a number that can be measured and tuned rather than
  // an emergent property of a contact solver.
  const wheelOptions: Matter.IBodyDefinition = {
    density: 0.008,
    friction: 0.002,
    frictionStatic: 0,
    restitution: 0.02,
    label: 'wheel',
  }
  // Tried and rejected: building these oversized with 200 sides and scaling
  // them down, on the theory that a 22px circle is really a 22-gon and a rig
  // that slides rather than rolls has to walk over every flat. It measured
  // WORSE - top speed 0.93 against 1.44 - so whatever is absorbing the drive
  // force at low tractive effort, it is not the faceting.
  const rearWheel = Matter.Bodies.circle(
    TRUCK_START_X + REAR_AXLE.x, startY + REAR_AXLE.y, WHEEL_R, wheelOptions,
  )
  const frontWheel = Matter.Bodies.circle(
    TRUCK_START_X + FRONT_AXLE.x, startY + FRONT_AXLE.y, WHEEL_R, wheelOptions,
  )

  const truckBody = Matter.Body.create({
    parts: [chassis, bed, headboard, rearLip, rearWheel, frontWheel],
    // This is the deck's grip, and the only friction the rig has - see the
    // note on the ground slabs above.
    friction: 1.2,
    label: 'truck',
  })
  // Stands in for rolling resistance and engine braking: lifting off has to
  // slow the rig down, or every descent ends at terminal velocity.
  truckBody.frictionAir = 0.02
  // Static friction is the max of the two parents, so this has to be zero or
  // the road holds the rig however low the road's own value is.
  truckBody.frictionStatic = 0

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
      // ---- the rig itself ----
      // Ground impacts only. A truck is wrecked by landing on the road, not
      // by what is on its back, and counting cargo here would have the rig
      // taking damage while it was being loaded.
      const aTruck = pair.bodyA.parent === truckBody
      const bTruck = pair.bodyB.parent === truckBody
      if (aTruck !== bTruck) {
        const ground = aTruck ? pair.bodyB : pair.bodyA
        if (ground.label === 'ground' && engine.timing.timestamp >= result.truckSettledAt) {
          const normal = pair.collision.normal
          const closing = Math.abs(
            truckBody.velocity.x * normal.x + truckBody.velocity.y * normal.y,
          )
          if (closing > TRUCK_DAMAGE_SPEED) {
            result.truckDamage = Math.min(
              1, result.truckDamage + (closing - TRUCK_DAMAGE_SPEED) * TRUCK_DAMAGE_SCALE,
            )
          }
        }
      }

      // ---- the load ----
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
        if (entry.state === 'gone') continue

        const threshold = entry.crate.fragile ? FRAGILE_SPEED : DAMAGE_SPEED
        if (closingSpeed > threshold) {
          const hit = Math.min(
            MAX_DAMAGE_PER_IMPACT, (closingSpeed - threshold) * DAMAGE_SCALE,
          )
          entry.damage = Math.min(1, entry.damage + hit)
        }
      }
    }
  }
  // collisionStart only. Resting contact re-fires collisionActive every
  // single frame, so including it charged a stationary crate 60 impacts a
  // second and destroyed every load before the truck had moved.
  Matter.Events.on(engine, 'collisionStart', onCollision)

  const bedTopOffset = startY - CHASSIS_H / 2 - BED_H - truckBody.position.y

  const result: TruckWorld = {
    engine,
    chassis: truckBody,
    rearWheel,
    frontWheel,
    cargo,
    finishX,
    contactDy: startY + CONTACT_DY - truckBody.position.y,
    throttle: 0,
    truckDamage: 0,
    slipping: false,
    braking: false,
    debris: [],
    shards: [],
    events: [],
    deckSoakedUntil: 0,
    fuel: 1,
    // The rig is built above the road and drops onto it. Without a grace
    // period that first landing is an impact like any other, and the truck
    // would start the run already dented.
    truckSettledAt: 600,
    // Held as an offset from the body's own origin and evaluated live, so
    // the deck follows the rig as it pitches over the terrain instead of
    // being frozen at the height it happened to be built at. Matter puts a
    // compound body's origin at its centre of mass, which is nowhere near
    // the chassis rectangle's centre once the wheels are parts of it, so
    // the offset has to be measured rather than assumed.
    bedTop: () => truckBody.position.y + bedTopOffset,
    hullOffset: { x: TRUCK_START_X - truckBody.position.x, y: startY - truckBody.position.y },
    deckLocalY: bedTopOffset,
    destroy: () => {
      Matter.Events.off(engine, 'collisionStart', onCollision)
      result.debris.length = 0
      result.shards.length = 0
      result.events.length = 0
      Matter.Composite.clear(world, false)
      Matter.Engine.clear(engine)
    },
  }
  return result
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
    if (existing.state !== 'deck') continue
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
    body, crate, w, h, damage: 0, state: 'deck',
    dryMass: body.mass,
    wetUntil: 0,
    settledAt: world.engine.timing.timestamp + 400,
  }
  world.cargo.push(entry)
  return entry
}

/** Throttle in [-1, 1]; negative reverses. */
/**
 * The whole drive model, as fractions of the rig's own weight.
 *
 * Every one of these is a force divided by weight, which is the same thing
 * as an acceleration in g. That makes them checkable against something real:
 * GRIP 0.32 is a laden truck pulling away briskly, BRAKE 0.22 is firm but
 * well short of a panic stop, and the steepest grade the road generator can
 * produce is 10 degrees, which costs sin(10) = 0.17g - so the rig climbs
 * anything it can meet, with room to spare.
 *
 * They are forces rather than contact friction because contact friction had
 * a break-away cliff in it: below it the rig could not exceed 2.6px a frame
 * however hard it was pushed, and above it there was nothing holding it at
 * all. The pedal has to map to the speed for the driving to feel like
 * anything, and that only works if the numbers are ours.
 *
 * Raised once already: at GRIP 0.32 and a cap of 4.5 the rig read as slow,
 * and a longer road made that worse rather than better. The relationship
 * between them is what matters - the cap decides the top speed and the grip
 * decides how long it takes to get there - so both moved together.
 */
const GRIP = 0.62
const BRAKE = 0.4
/** Rolling resistance. Small, constant, and the thing that finally stops it. */
const ROLL = 0.01
/**
 * The parking brake, as a fraction of weight.
 *
 * Big enough that its band covers the whole "stopped" range. At 0.3 the
 * brake only engaged below 0.12px a frame while gravity on a slope adds
 * 0.07 every frame, so the rig spent alternate frames inside and outside
 * the band and crept downhill at 0.03px a frame - visible as the entire
 * scene drifting while the truck sat still being loaded. Nothing in the
 * game is steep enough to overcome 0.9g, which is the intent: a parked
 * truck stays where it was parked.
 */
const HOLD = 0.9
/** Below this the rig counts as stopped, for holding and for picking up. */
const STOPPED = 0.35

/** Top speed the throttle will push to. Exported so the checks can express
 *  a driving style as a fraction of it rather than a bare number that goes
 *  stale the moment the rig is retuned. */
export const MAX_SPEED = 7.6

/**
 * Fuel burn per second: a fixed amount for having the engine running, and
 * the same again at full throttle.
 *
 * The tank is what stops a run being free.
 *
 * Until it existed, driving carefully had no cost at all - you could crawl
 * the whole route, reverse back for everything you dropped, and collect
 * around 90% every time, so there was no decision anywhere in the game.
 * This is the genre's standard answer to that. Hill Climb Racing uses fuel
 * as a timer for exactly this reason, and Cargo, Please! states the trade
 * plainly: reckless driving risks the cargo, cautious driving costs you
 * time. Now it costs fuel, which is the same thing with a gauge on it.
 *
 * Idle and drive are deliberately equal, so TIME on the route costs as much
 * as THROTTLE does. If idle were negligible, crawling would still be free;
 * if throttle were negligible, flooring it would be. Measured over the real
 * routes: a brisk run uses about two thirds of the tank, a careful one
 * finishes with very little left, and a detour to pick up a dropped crate
 * costs about a fifth of it. So every one of those is now a choice.
 */
const FUEL_IDLE_PER_SECOND = 0.0147
const FUEL_DRIVE_PER_SECOND = 0.0147

/** (1000/60)^2 - see coast(). Matter scales an applied force by this. */
const STEP_SQUARED = (1000 / 60) ** 2
/**
 * The top of the speed range, where power tapers off.
 *
 * Full force up to 82% of the cap and a linear fade above it. A hard cutoff
 * makes the rig hit its top speed like a wall; a gentle curve over the whole
 * range (the first attempt) made it take fifteen seconds to get near the cap
 * at all, which read as a truck with no engine.
 */
const TAPER_FROM = 0.82

/**
 * How fast the throttle itself may move, per step.
 *
 * Applying full force the instant a key goes down is dumping the clutch:
 * the deck accelerates out from under the load, and a crate was measured
 * sliding straight off the back within seconds of pulling away. Easing the
 * force in over about a third of a second is what a driver with a load on
 * actually does, and it makes the pedal something you can be gentle with.
 */
const THROTTLE_RATE = 0.012

/**
 * Gear tops, as fractions of the rig's top speed.
 *
 * A loaded truck does not simply accelerate: it pulls hard from rest, runs
 * out of that gear, shifts, and pulls again. Without this the rig went from
 * standing to full speed in about six tenths of a second, which is what a
 * hot hatch does and reads as one.
 *
 * Modelled as a sawtooth on the tractive force rather than with a shift
 * timer: full pull at the bottom of each gear and less at the top of it, so
 * the acceleration visibly steps as it climbs, and no state has to be kept
 * between frames.
 *
 * The dip is shallow - a quarter - and that is not a style choice. Below
 * roughly 0.5g of tractive effort the rig cannot get moving on the ground
 * at all, whatever the arithmetic says it should do; measured with air drag
 * and rolling resistance both switched off, a force that accelerates it
 * cleanly to 25px a frame in open space leaves it sitting at 1.4 on the
 * road. A deeper sawtooth would drop it under that floor at every gear
 * change and stall it. Most of the gradual pull-away comes from the
 * throttle ramp instead, which is a slower and much safer lever.
 */
const GEARS = [0.16, 0.34, 0.55, 0.78, 1]
/** How much of the pull is left at the top of a gear, before the change. */
const GEAR_FALLOFF = 0.25

/** Where in the current gear the rig is, as a multiplier on its pull. */
function gearPull(speed: number): number {
  const ratio = Math.min(1, speed / MAX_SPEED)
  let floor = 0
  for (const top of GEARS) {
    if (ratio <= top) {
      const through = (ratio - floor) / (top - floor)
      return 1 - GEAR_FALLOFF * through
    }
    floor = top
  }
  return 1 - GEAR_FALLOFF
}

/**
 * A force of `g` times the weight the tyres are carrying - the rig plus
 * whatever is riding on it.
 *
 * The load has to be in here. Matter applies the force to the chassis body
 * alone, but the chassis then has to drag the cargo along through deck
 * friction, so scaling by the rig's own mass gave a loaded truck a top speed
 * of 2.1 against an empty one's 4.0. Scaling by everything it is moving
 * keeps the acceleration roughly constant, which is what a driver does with
 * a real one: more throttle for a heavier load.
 */
function weightForce(world: TruckWorld, g: number): number {
  const gravity = world.engine.gravity
  let mass = world.chassis.mass
  for (const entry of world.cargo) {
    // Dry mass, deliberately. Water taken on makes the rig heavier to move
    // without giving the tyres anything more to push against, which is what
    // makes a soaked load pull away like one.
    if (entry.state === 'deck') mass += entry.dryMass
  }
  return g * mass * gravity.y * gravity.scale
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

/**
 * Throttle in [-1, 1]; negative reverses.
 *
 * Called once per step for the whole of the run, including when the player
 * is asking for nothing - the engine is running either way, and that is
 * what makes time cost fuel.
 */
export function drive(world: TruckWorld, throttle: number) {
  const target = Math.max(-1, Math.min(1, throttle))
  const delta = target - world.throttle
  world.throttle += Math.max(-THROTTLE_RATE, Math.min(THROTTLE_RATE, delta))

  world.fuel = Math.max(0, world.fuel - (
    FUEL_IDLE_PER_SECOND + FUEL_DRIVE_PER_SECOND * Math.abs(world.throttle)
  ) / 60)

  const vx = world.chassis.velocity.x
  world.slipping = false

  // Dry. The rig rolls to a halt on what momentum it has; coast() takes it
  // from there.
  if (world.fuel <= 0) {
    world.throttle = 0
    return
  }

  if (Math.abs(world.throttle) < 0.01) return

  // Power fades over the last stretch of the range rather than being cut off.
  const sameWay = Math.sign(vx) === Math.sign(world.throttle)
  const fade = sameWay
    ? Math.max(0, Math.min(1, (MAX_SPEED - Math.abs(vx)) / (MAX_SPEED * (1 - TAPER_FROM))))
    : 1
  if (fade <= 0) return

  // Asking for everything while barely moving is the tyres losing rather
  // than the rig accelerating - worth showing, since it is the moment the
  // driver should ease off.
  world.slipping = Math.abs(world.throttle) > 0.9 && Math.abs(vx) < 0.4
  applyAtRoad(
    world,
    world.throttle * fade * gearPull(Math.abs(vx)) * weightForce(world, GRIP),
  )
}

/**
 * Slows the rig down, within what the tyres could hold.
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
  world.braking = true
  applyAtRoad(world, -Math.sign(vx) * weightForce(world, BRAKE))
}

/**
 * Everything the road does to the rig when nobody is asking it for
 * anything: rolling resistance, and enough of a hold that a parked truck
 * stays parked instead of creeping off down the nearest slope.
 *
 * Called every step, whatever the player is doing - rolling resistance does
 * not stop applying because the throttle is down.
 */
export function coast(world: TruckWorld) {
  const vx = world.chassis.velocity.x
  const speed = Math.abs(vx)
  if (speed < 0.005) return

  // The force that would cancel the current velocity exactly this step.
  // Matter turns a force into a velocity change as (f / mass) * dt^2, with
  // dt fixed at 1000/60 here, so dt^2 is 277.8.
  const cancelling = (-vx * world.chassis.mass) / STEP_SQUARED

  if (speed < STOPPED && Math.abs(world.throttle) < 0.05 && !world.braking) {
    // The parking brake.
    //
    // A force cannot do this job. Cancelling the velocity with one leaves
    // gravity free to put it back on the very next step, so on any slope the
    // rig sat in a loop - accelerate, cancel, accelerate - and crept
    // downhill at 0.03px a frame for ever, which reads on screen as the
    // whole scene drifting. Setting the velocity outright is what a brake
    // actually does, and the road under these wheels is frictionless by
    // design, so nothing else was ever going to hold it.
    //
    // The limit still matters: past it the brake is overwhelmed and the rig
    // rolls, which is what should happen on something genuinely steep.
    const limit = weightForce(world, HOLD)
    if (Math.abs(cancelling) <= limit) {
      Matter.Body.setVelocity(world.chassis, { x: 0, y: world.chassis.velocity.y })
      return
    }
    // At the centre of mass, not the road: this is a distributed hold, and
    // putting it at the contact line would pitch a stationary rig.
    Matter.Body.applyForce(
      world.chassis, world.chassis.position, { x: Math.sign(cancelling) * limit, y: 0 },
    )
    return
  }

  const roll = weightForce(world, ROLL)
  applyAtRoad(world, Math.max(-roll, Math.min(roll, cancelling)))
}

/**
 * Blows the rig apart.
 *
 * The compound body leaves the world and a dozen loose pieces take its
 * place, thrown outward and left to the physics like anything else. Drawing
 * a burst over an intact truck was the cheap version and it read as one:
 * the truck was plainly still sitting there afterwards. The load goes with
 * it, since none of it is arriving now either.
 */
export function explodeTruck(world: TruckWorld) {
  if (world.debris.length > 0) return
  const { x, y } = world.chassis.position
  Matter.Composite.remove(world.engine.world, world.chassis)

  // Math.random is fine here and nowhere else in this file: the wreck is
  // cosmetic, happens after the run is over, and is never scored.
  const spread = (n: number) => (Math.random() - 0.5) * n
  for (let i = 0; i < 14; i++) {
    const w = 9 + Math.random() * 20
    const h = 6 + Math.random() * 14
    const piece = Matter.Bodies.rectangle(x + spread(200), y + spread(46), w, h, {
      friction: 0.5,
      restitution: 0.25,
      angle: Math.random() * Math.PI,
      label: 'debris',
    })
    Matter.Body.setVelocity(piece, { x: spread(13), y: -3.5 - Math.random() * 8 })
    Matter.Body.setAngularVelocity(piece, spread(0.7))
    world.debris.push(piece)
  }
  // The wheels come off as wheels - they are the one part of a truck that
  // stays recognisable in a wreck.
  for (const wheel of [world.rearWheel, world.frontWheel]) {
    const tyre = Matter.Bodies.circle(wheel.position.x, wheel.position.y, WHEEL_R, {
      friction: 0.6, restitution: 0.4, label: 'tyre',
    })
    Matter.Body.setVelocity(tyre, { x: spread(11), y: -4 - Math.random() * 5 })
    Matter.Body.setAngularVelocity(tyre, spread(0.9))
    world.debris.push(tyre)
  }
  Matter.Composite.add(world.engine.world, world.debris)

  for (const entry of world.cargo) {
    if (entry.state !== 'deck') continue
    entry.state = 'road'
    Matter.Body.setVelocity(entry.body, { x: spread(9), y: -2 - Math.random() * 6 })
    Matter.Body.setAngularVelocity(entry.body, spread(0.5))
  }
}

/** Marks cargo that has fallen off the truck or off the world. */
export function updateCargoState(world: TruckWorld) {
  dryOut(world)
  for (const entry of world.cargo) {
    if (entry.state === 'gone') continue

    // Finished off. Worth nothing either way, but what it does on the way
    // out depends on what was in it.
    if (entry.damage >= 0.999) {
      destroyCargo(world, entry)
      continue
    }

    // Off the bottom of the world - through a seam, or thrown clear off the
    // end of the road. Nothing to go back for.
    if (entry.body.position.y > BASE_GROUND_Y + 500) {
      entry.state = 'gone'
      entry.damage = 1
      continue
    }
    if (entry.state !== 'deck') continue

    // Measured in the rig's own frame, not the world's.
    //
    // The world-frame version asked whether the item was 250px away
    // horizontally or 70px down, which meant something that had slid off and
    // was lying right beside the wheels still counted as loaded - so it could
    // not be picked up until the truck had driven a quarter of a screen away
    // from it, which is the opposite of what a driver would do. In the rig's
    // frame the question is the real one: is it still above the deck, and
    // still between the headboard and the rear lip.
    const dx = entry.body.position.x - world.chassis.position.x
    const dy = entry.body.position.y - world.chassis.position.y
    const cos = Math.cos(-world.chassis.angle)
    const sin = Math.sin(-world.chassis.angle)
    const alongDeck = dx * cos - dy * sin
    const aboveDeck = dx * sin + dy * cos

    // A little slack at both ends: a crate can overhang the lip slightly and
    // still be riding, and the deck surface itself is solid, so nothing that
    // is genuinely on it can ever be below this line.
    const offTheSide = alongDeck < DECK_MIN_OFFSET - 26 || alongDeck > DECK_MAX_OFFSET + 26
    const belowTheDeck = aboveDeck > world.deckLocalY + 10
    if (offTheSide || belowTheDeck) {
      entry.state = 'road'
      // The road is frictionless for the rig's benefit, so something that
      // lands on it would otherwise skate away for ever. Air drag stands in
      // for the grip the surface is not allowed to have.
      entry.body.frictionAir = ROAD_DRAG
    }
  }
}

/**
 * What happens when a piece of freight is finished off.
 *
 * Everything comes apart - the body is replaced by a handful of loose
 * fragments, because a destroyed crate that carries on looking like a crate
 * gives the player no way to tell the difference between a total loss and a
 * badly dented one.
 *
 * What was inside it then decides whether that is the end of the matter. A
 * placarded drum is worth more to haul for the same reason it is worse to
 * break, which is the trade the loading screen is really offering:
 *
 *   flammable - it goes up, and takes a large bite out of the rig with it.
 *               Anything nearby is thrown clear.
 *   liquid    - it bursts over the deck. The rig takes a little damage, and
 *               for the rest of the run the deck is wet, so nothing left on
 *               it grips the way it did.
 */
const SHATTER_PIECES = 6
/** Rig damage from a drum of something flammable letting go on the deck. */
const BLAST_DAMAGE = 0.45
const BLAST_RADIUS = 210
const SPILL_DAMAGE = 0.12
/** What is left of the deck's grip once a liquid load has burst over it. */
const SOAKED_FRICTION = 0.3
/** How far a spill reaches across the deck. */
const SPILL_RADIUS = 150
/** How much heavier a soaked item gets. Water is not light. */
const SOAKED_MASS = 1.5
/**
 * How long a spill takes to drain and dry, in engine milliseconds.
 *
 * Temporary on purpose. A permanent slippery deck turns one burst drum into
 * a run that is already over, which is a punishment rather than a problem to
 * drive around - and driving around it is the interesting part: ease off,
 * get through the next few hills gently, and it comes back.
 */
const DRY_OUT_MS = 15000

function destroyCargo(world: TruckWorld, entry: CargoBody) {
  const { x, y } = entry.body.position
  entry.state = 'gone'
  entry.damage = 1
  Matter.Composite.remove(world.engine.world, entry.body)

  // Math.random is fine for wreckage: it is cosmetic, and nothing about a
  // destroyed item is scored beyond the fact that it is destroyed.
  const spread = (n: number) => (Math.random() - 0.5) * n
  const size = Math.max(5, Math.min(entry.w, entry.h) / 3)
  for (let i = 0; i < SHATTER_PIECES; i++) {
    const piece = Matter.Bodies.rectangle(
      x + spread(entry.w * 0.7), y + spread(entry.h * 0.7),
      size * (0.6 + Math.random() * 0.8), size * (0.6 + Math.random() * 0.8),
      { friction: 0.6, restitution: 0.2, angle: Math.random() * Math.PI, label: 'shard' },
    )
    Matter.Body.setVelocity(piece, { x: spread(6), y: -1.5 - Math.random() * 4 })
    Matter.Body.setAngularVelocity(piece, spread(0.5))
    world.shards.push({ body: piece, kind: entry.crate.kind })
    Matter.Composite.add(world.engine.world, piece)
  }
  world.events.push({ kind: 'shatter', x, y })

  if (entry.crate.hazard === 'flammable') {
    world.events.push({ kind: 'blast', x, y })

    // The rig, if it is close enough to be caught in it.
    const reach = Math.hypot(x - world.chassis.position.x, y - world.chassis.position.y)
    if (reach < BLAST_RADIUS) {
      const share = 1 - reach / BLAST_RADIUS
      world.truckDamage = Math.min(1, world.truckDamage + BLAST_DAMAGE * share)
      // And it is shoved. A blast that leaves the truck sitting exactly where
      // it was reads as a decal rather than an explosion.
      Matter.Body.setVelocity(world.chassis, {
        x: world.chassis.velocity.x + Math.sign(world.chassis.position.x - x || 1) * share * 3.5,
        y: world.chassis.velocity.y - share * 4.5,
      })
      Matter.Body.setAngularVelocity(world.chassis, world.chassis.angularVelocity - share * 0.09)
    }

    // Everything else near it is thrown clear AND scorched. Being next to a
    // drum that goes up has to cost something, or placing the dangerous item
    // beside the valuable one carries no risk at all.
    for (const other of world.cargo) {
      if (other === entry || other.state === 'gone') continue
      const dist = Math.hypot(other.body.position.x - x, other.body.position.y - y)
      if (dist > BLAST_RADIUS) continue
      const share = 1 - dist / BLAST_RADIUS
      other.damage = Math.min(1, other.damage + share * BLAST_DAMAGE)
    }

    const nearby: Matter.Body[] = [
      ...world.cargo.filter((c) => c.state !== 'gone').map((c) => c.body),
      ...world.shards.map((sh) => sh.body),
    ]
    for (const body of nearby) {
      const dx = body.position.x - x
      const dy = body.position.y - y
      const dist = Math.hypot(dx, dy)
      if (dist > BLAST_RADIUS || dist < 0.001) continue
      const push = (1 - dist / BLAST_RADIUS) * 7
      Matter.Body.setVelocity(body, {
        x: body.velocity.x + (dx / dist) * push,
        y: body.velocity.y + (dy / dist) * push - 2,
      })
    }
  } else if (entry.crate.hazard === 'liquid') {
    world.events.push({ kind: 'spill', x, y })
    world.truckDamage = Math.min(1, world.truckDamage + SPILL_DAMAGE)
    soakDeck(world)
    // Anything it runs over takes it on. A soaked crate is heavier and holds
    // the water until it dries.
    for (const other of world.cargo) {
      if (other === entry || other.state === 'gone') continue
      const dist = Math.hypot(other.body.position.x - x, other.body.position.y - y)
      if (dist > SPILL_RADIUS) continue
      soakCargo(world, other)
    }
  }
}

/** Wets one item: heavier until it dries, and visibly so. */
function soakCargo(world: TruckWorld, entry: CargoBody) {
  entry.wetUntil = world.engine.timing.timestamp + DRY_OUT_MS
  Matter.Body.setMass(entry.body, entry.dryMass * SOAKED_MASS)
}

/** Wets the deck, so nothing on it grips properly until it dries. */
function soakDeck(world: TruckWorld) {
  const alreadyWet = world.deckSoakedUntil > world.engine.timing.timestamp
  world.deckSoakedUntil = world.engine.timing.timestamp + DRY_OUT_MS
  if (alreadyWet) return
  // On the parent, because that is where the deck's grip actually lives.
  world.chassis.friction *= SOAKED_FRICTION
}

/** Puts the grip and the weight back once everything has dried out. */
function dryOut(world: TruckWorld) {
  const now = world.engine.timing.timestamp
  if (world.deckSoakedUntil > 0 && now >= world.deckSoakedUntil) {
    world.deckSoakedUntil = 0
    world.chassis.friction /= SOAKED_FRICTION
  }
  for (const entry of world.cargo) {
    if (entry.wetUntil > 0 && now >= entry.wetUntil) {
      entry.wetUntil = 0
      if (entry.state !== 'gone') Matter.Body.setMass(entry.body, entry.dryMass)
    }
  }
}

/**
 * How far back the driver can reach for something they dropped, and how
 * close to stopped they have to be to try.
 *
 * Generous on distance and strict on speed: hunting for a pixel-perfect
 * parking spot is not the interesting part, but scooping a crate up at
 * twenty miles an hour would make dropping things free.
 */
export const RECOVER_REACH = 260
// Nearly stopped, not perfectly stopped. At 0.35 the rig had to be dead
// still, which on any slope it never quite is.
const RECOVER_MAX_SPEED = 0.7

/** Items on the road that the truck is currently in a position to collect. */
export function recoverableCargo(world: TruckWorld): CargoBody[] {
  if (Math.abs(world.chassis.velocity.x) > RECOVER_MAX_SPEED) return []
  return world.cargo.filter(
    (entry) => entry.state === 'road'
      && Math.abs(entry.body.position.x - world.chassis.position.x) < RECOVER_REACH,
  )
}

/**
 * Puts a dropped item back on the deck.
 *
 * The same body, moved - not a fresh one - so the damage it took on the way
 * down stays with it. It gets the same settling grace a newly loaded item
 * gets, because being set down by hand is not an impact.
 */
export function reloadCargo(
  world: TruckWorld, entry: CargoBody, offsetX: number, rotated: boolean,
) {
  const spot = planDrop(world, entry.crate, offsetX, rotated)
  Matter.Body.setAngle(entry.body, 0)
  Matter.Body.setAngularVelocity(entry.body, 0)
  Matter.Body.setVelocity(entry.body, { x: 0, y: 0 })
  Matter.Body.setPosition(entry.body, { x: spot.x, y: spot.y })
  entry.w = spot.w
  entry.h = spot.h
  entry.state = 'deck'
  entry.body.frictionAir = 0.01
  entry.settledAt = world.engine.timing.timestamp + 400
}

/** What the run is worth right now - damaged cargo pays proportionally. */
export function currentPayout(world: TruckWorld): number {
  // Only what is actually on the deck. An item lying on the road behind you
  // is worth nothing at the drop, however good a condition it is in.
  return world.cargo.reduce(
    (sum, entry) => (entry.state === 'deck'
      ? sum + Math.round(entry.crate.rate * (1 - entry.damage))
      : sum),
    0,
  )
}
