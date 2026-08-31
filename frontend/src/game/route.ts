/**
 * Seeded route generation.
 *
 * Kept deliberately pure and dependency-free, because the SERVER runs this
 * same generator when it validates a submitted score: given the seed it
 * issued, it can work out how much cargo that route carried and therefore
 * the highest score physically obtainable on it. A client claiming more than
 * that is rejected. That check is only as good as both sides agreeing on the
 * route, so this file must stay free of Math.random, Date.now, and anything
 * else that differs between the two.
 *
 * Mirrored in Python at services/game_route.py - change one, change both,
 * and the shared test vectors in tests/test_game_route.py will catch it if
 * they drift.
 */

/** Terrain is a series of ground heights sampled every SEGMENT_WIDTH px. */
export const SEGMENT_WIDTH = 40
// ~3.6km of road. 160 made a careful run take three to four minutes,
// which is a commute, not a coffee break.
export const ROUTE_SEGMENTS = 90
export const BASE_GROUND_Y = 420

/**
 * What kind of thing this is, which is really a statement about its centre
 * of gravity. A pallet is wide and low and forgiving; a drum stands tall on
 * a small footprint and will go over on the first camber unless it is laid
 * down or braced by something beside it.
 */
export type CrateKind = 'pallet' | 'crate' | 'drum'

export interface Crate {
  /** Kilograms - drives both the physics mass and the payout. */
  weight: number
  kind: CrateKind
  /** Footprint in pixels, upright. The player can rotate when loading. */
  w: number
  h: number
  /** What this crate pays if it arrives undamaged. */
  rate: number
  fragile: boolean
}

export interface Route {
  seed: number
  /** Ground height at each sample point, left to right. */
  heights: number[]
  crates: Crate[]
  /** Total payout if every crate arrives untouched - the server's ceiling. */
  maxPayout: number
  distance: number
}

/**
 * Mulberry32. A small, fast, well-distributed 32-bit PRNG.
 *
 * Chosen over anything using floating point internally because the server
 * has to reproduce these exact numbers: this is pure integer math until the
 * final divide, so JavaScript and Python agree bit for bit.
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Picks an integer in [min, max]. */
function randInt(rand: () => number, min: number, max: number): number {
  return min + Math.floor(rand() * (max - min + 1))
}

export function generateRoute(seed: number): Route {
  const rand = mulberry32(seed)

  // Terrain: a slow rolling base with occasional sharper features. Built by
  // walking a height value rather than sampling a noise function, so it can
  // never produce a step the truck physically cannot climb.
  const heights: number[] = []
  let height = BASE_GROUND_Y
  let slope = 0
  for (let i = 0; i < ROUTE_SEGMENTS; i++) {
    // The first stretch is deliberately flat - the load has to survive
    // pulling away before the route starts testing it.
    if (i < 6) {
      heights.push(BASE_GROUND_Y)
      continue
    }

    // Nudge the slope rather than the height, which is what makes the ground
    // read as continuous terrain instead of noise.
    slope += (rand() - 0.5) * 3.2
    slope = Math.max(-7, Math.min(7, slope))
    height += slope
    // Keep it on screen and away from a wall the truck can't crest.
    height = Math.max(BASE_GROUND_Y - 90, Math.min(BASE_GROUND_Y + 70, height))

    // Occasional pothole - a single sharp dip, the classic way to lose a
    // badly balanced load. Kept well under the 22px wheel radius: a step
    // taller than the wheel is not a bump, it is a wall, and the rig simply
    // stops dead against it with no way for the player to tell why.
    if (i > 12 && rand() < 0.06) {
      height += randInt(rand, 5, 11)
      slope = 0
    }
    heights.push(height)
  }

  // Cargo: 3-6 items, mixed weights and mixed shapes. Fragile ones pay more
  // and take damage from smaller impacts, so the load-out is a real decision
  // rather than "take everything".
  const crateCount = randInt(rand, 3, 6)
  const crates: Crate[] = []
  for (let i = 0; i < crateCount; i++) {
    const weight = randInt(rand, 2, 8) * 100
    const fragile = rand() < 0.35
    const roll = rand()
    const kind: CrateKind = roll < 0.38 ? 'pallet' : roll < 0.76 ? 'crate' : 'drum'

    // Dimensions are whole multiples of a per-weight unit, never a rounded
    // float. Math.round and Python's round() disagree on exact halves, and
    // the server has to reproduce these numbers - so there are no halves to
    // disagree about. weight is a multiple of 100, so weight / 100 is exact.
    const unit = 5 + weight / 100
    const spans: Record<CrateKind, [number, number]> = {
      pallet: [5, 2],
      crate: [3, 3],
      drum: [2, 4],
    }
    const [wu, hu] = spans[kind]

    crates.push({
      weight,
      kind,
      w: unit * wu,
      h: unit * hu,
      // Round hundreds, scaled off weight, with a premium for fragile.
      rate: Math.round((weight * 0.9 + (fragile ? 400 : 0)) / 50) * 50,
      fragile,
    })
  }

  return {
    seed,
    heights,
    crates,
    maxPayout: crates.reduce((sum, c) => sum + c.rate, 0),
    distance: ROUTE_SEGMENTS * SEGMENT_WIDTH,
  }
}
