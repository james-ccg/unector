"""
Server-side twin of frontend/src/game/route.ts.

The leaderboard can't trust a score the client simply asserts, so the server
issues the seed and then reproduces the route from it. That gives an upper
bound on what the route could possibly pay, which any submitted score has to
fit inside. Everything here therefore has to match the TypeScript version
exactly - same PRNG, same call order, same rounding.

Kept as integer math right up to the final divide for that reason: floating
point is where two implementations of "the same" generator quietly stop
agreeing. tests/test_game_route.py pins both sides to shared vectors.
"""
from dataclasses import dataclass

SEGMENT_WIDTH = 40
ROUTE_SEGMENTS = 90
BASE_GROUND_Y = 420

_UINT32 = 0xFFFFFFFF


#: Footprint in whole units, upright: (width, height). A pallet is wide and
#: low and forgiving; a drum stands tall on a small footprint and goes over
#: on the first camber unless it is laid down or braced.
CRATE_SPANS = {
    "pallet": (5, 2),
    "crate": (3, 3),
    "drum": (2, 4),
}


@dataclass(frozen=True)
class Crate:
    weight: int
    kind: str
    w: int
    h: int
    rate: int
    fragile: bool


@dataclass(frozen=True)
class Route:
    seed: int
    heights: list[float]
    crates: list[Crate]
    max_payout: int
    distance: int


def _imul(a: int, b: int) -> int:
    """JavaScript's Math.imul: 32-bit signed integer multiply.

    Python ints are arbitrary precision, so without this the PRNG diverges
    from the browser on the very first call."""
    result = (a * b) & _UINT32
    return result - 0x100000000 if result >= 0x80000000 else result


def mulberry32(seed: int):
    """Bit-for-bit port of the mulberry32 in route.ts."""
    a = seed & _UINT32

    def rand() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _UINT32
        t = a
        t = _imul(t ^ (t >> 15), t | 1) & _UINT32
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & _UINT32
        t &= _UINT32
        return ((t ^ (t >> 14)) & _UINT32) / 4294967296

    return rand


def _rand_int(rand, low: int, high: int) -> int:
    return low + int(rand() * (high - low + 1))


def generate_route(seed: int) -> Route:
    rand = mulberry32(seed)

    heights: list[float] = []
    height = float(BASE_GROUND_Y)
    slope = 0.0
    for i in range(ROUTE_SEGMENTS):
        if i < 6:
            heights.append(float(BASE_GROUND_Y))
            continue

        slope += (rand() - 0.5) * 3.2
        slope = max(-7.0, min(7.0, slope))
        height += slope
        height = max(BASE_GROUND_Y - 90, min(BASE_GROUND_Y + 70, height))

        # Kept under the wheel radius - see the note in route.ts.
        if i > 12 and rand() < 0.06:
            height += _rand_int(rand, 5, 11)
            slope = 0.0
        heights.append(height)

    crate_count = _rand_int(rand, 3, 6)
    crates: list[Crate] = []
    for _ in range(crate_count):
        weight = _rand_int(rand, 2, 8) * 100
        fragile = rand() < 0.35
        roll = rand()
        kind = "pallet" if roll < 0.38 else "crate" if roll < 0.76 else "drum"

        # Whole multiples of a per-weight unit, never a rounded float:
        # round() here is banker's rounding and Math.round() in the browser
        # is not, so an exact half would silently split the two sides apart.
        # weight is always a multiple of 100, so weight // 100 is exact.
        unit = 5 + weight // 100
        wu, hu = CRATE_SPANS[kind]

        crates.append(
            Crate(
                weight=weight,
                kind=kind,
                w=unit * wu,
                h=unit * hu,
                rate=round((weight * 0.9 + (400 if fragile else 0)) / 50) * 50,
                fragile=fragile,
            )
        )

    return Route(
        seed=seed,
        heights=heights,
        crates=crates,
        max_payout=sum(c.rate for c in crates),
        distance=ROUTE_SEGMENTS * SEGMENT_WIDTH,
    )
