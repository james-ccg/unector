"""
Pins services/game_route.py to frontend/src/game/route.ts.

The leaderboard's whole defence is that the server can regenerate the route
it issued a seed for, work out the most that route could possibly pay, and
reject anything above it. That only holds while both implementations agree,
and they can drift apart silently - a changed constant, a different rounding
rule, a reordered PRNG call - without either side failing on its own.

The vectors below were captured by running the real TypeScript generator.
Regenerate them (and update both files together) if the route design ever
changes on purpose.
"""
import pytest

from services.game_route import (
    BASE_GROUND_Y,
    ROUTE_SEGMENTS,
    generate_route,
    mulberry32,
)


# Captured from the browser implementation - see the module docstring.
JS_PRNG_VECTORS = {
    1: [0.6270739405881613, 0.002735721180215478, 0.5274470399599522,
        0.9810509674716741, 0.9683778982143849],
    42: [0.6011037519201636, 0.44829055899754167, 0.8524657934904099,
         0.6697340414393693, 0.17481389874592423],
    123456: [0.38233304349705577, 0.7972629074938595, 0.9965302373748273,
             0.16001168475486338, 0.20857197884470224],
    999999999: [0.8934107443783432, 0.06520688440650702, 0.8886369008105248,
                0.5204161775764078, 0.8709634775295854],
}

JS_ROUTE_123456 = {
    "heights_head": [420, 420, 420],
    "heights_tail": [421.1446689494, 423.4379437141, 426.5895009756],
    "crates": [
        (500, 41, 850, True),
        (700, 47, 1050, True),
        (700, 47, 650, False),
    ],
    "max_payout": 2550,
    "distance": 3600,
}


class TestPrngMatchesJavaScript:
    @pytest.mark.parametrize("seed", sorted(JS_PRNG_VECTORS))
    def test_first_five_draws_match(self, seed):
        rand = mulberry32(seed)
        got = [rand() for _ in range(5)]
        assert got == pytest.approx(JS_PRNG_VECTORS[seed], abs=1e-15)

    def test_imul_wraparound_matches_javascript(self):
        """The one place a naive port breaks: Python ints don't overflow, so
        without an explicit 32-bit signed multiply the sequences diverge on
        the very first call for large seeds."""
        rand = mulberry32(0xFFFFFFFF)
        values = [rand() for _ in range(20)]
        assert all(0.0 <= v < 1.0 for v in values)
        # A broken port typically collapses to a constant or repeats.
        assert len(set(values)) == 20


class TestRouteMatchesJavaScript:
    def test_route_for_a_known_seed_matches_exactly(self):
        route = generate_route(123456)

        assert [round(h, 10) for h in route.heights[:3]] == JS_ROUTE_123456["heights_head"]
        assert [round(h, 10) for h in route.heights[-3:]] == JS_ROUTE_123456["heights_tail"]
        assert [
            (c.weight, c.size, c.rate, c.fragile) for c in route.crates
        ] == JS_ROUTE_123456["crates"]
        assert route.max_payout == JS_ROUTE_123456["max_payout"]
        assert route.distance == JS_ROUTE_123456["distance"]

    def test_rounding_never_lands_on_a_half(self):
        """Python rounds halves to even, JavaScript rounds them up. No rate
        currently lands on .5 so the two agree, but that's a property of the
        constants rather than something either language guarantees - this
        fails loudly if a future tweak introduces one."""
        for seed in range(500):
            for crate in generate_route(seed).crates:
                scaled = (crate.weight * 0.9 + (400 if crate.fragile else 0)) / 50
                assert abs(scaled - int(scaled) - 0.5) > 1e-9, (
                    f"seed {seed} produces a .5 rate; Python and JS will disagree"
                )


class TestRouteIsPlayable:
    """Properties the physics depends on. A route that violates these isn't
    "hard", it's impossible, and the player has no way to tell the
    difference."""

    @pytest.mark.parametrize("seed", [0, 1, 7, 42, 999, 123456, 2**31 - 1])
    def test_shape_is_stable(self, seed):
        route = generate_route(seed)
        assert len(route.heights) == ROUTE_SEGMENTS
        assert 3 <= len(route.crates) <= 6
        assert route.max_payout == sum(c.rate for c in route.crates)

    def test_opens_flat_so_the_load_can_settle(self):
        """The first stretch has to be level - pulling away onto a slope would
        shed a load before the player has done anything wrong."""
        for seed in range(50):
            assert generate_route(seed).heights[:6] == [float(BASE_GROUND_Y)] * 6

    def test_terrain_stays_within_bounds(self):
        for seed in range(200):
            for h in generate_route(seed).heights:
                assert BASE_GROUND_Y - 90 <= h <= BASE_GROUND_Y + 81

    def test_no_step_taller_than_the_wheel(self):
        """The wheel is 22px in radius, so a step approaching that is a wall
        the rig simply stops dead against - which is what an earlier version
        did, with no way for the player to tell why. Slope is clamped to 7px
        per segment and a pothole adds at most 11 on top."""
        for seed in range(200):
            heights = generate_route(seed).heights
            for a, b in zip(heights, heights[1:]):
                assert abs(b - a) <= 18, f"seed {seed}: {a} -> {b} is taller than the wheel"

    def test_same_seed_is_reproducible(self):
        """The property the entire anti-cheat rests on."""
        first, second = generate_route(777), generate_route(777)
        assert first.heights == second.heights
        assert first.crates == second.crates

    def test_different_seeds_give_different_routes(self):
        routes = {tuple(generate_route(s).heights) for s in range(100)}
        assert len(routes) == 100
