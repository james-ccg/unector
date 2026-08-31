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
    CRATE_SPANS,
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
    "heights_tail": [606.2066412255, 609.4597806849, 613.9702732518],
    # (weight, kind, w, h, rate, fragile)
    "crates": [
        (300, "pallet", 40, 16, 650, True),
        (800, "crate", 39, 39, 700, False),
        (700, "crate", 36, 36, 1050, True),
        (800, "drum", 26, 52, 700, False),
        (200, "pallet", 35, 14, 600, True),
    ],
    "max_payout": 3700,
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
            (c.weight, c.kind, c.w, c.h, c.rate, c.fragile) for c in route.crates
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
                assert BASE_GROUND_Y - 90 <= h <= BASE_GROUND_Y + 320

    def test_the_road_never_steps_up_taller_than_the_wheel(self):
        """Direction matters, and only one of the two is dangerous.

        The road dropping away is a feature - the rig flies off it, and that
        is the only thing on these routes that can damage the truck. The road
        rising by more than the 22px wheel radius is not a bump but a wall
        the rig stops dead against, with no way for the player to tell why.
        Bigger y is lower ground, so a rise is a DECREASE.

        Slope is clamped to 7px per segment and every feature only ever adds,
        so nothing should rise at all beyond the slope."""
        for seed in range(300):
            heights = generate_route(seed).heights
            for a, b in zip(heights, heights[1:]):
                assert a - b <= 18, f"seed {seed}: {a} -> {b} is a wall, not a bump"

    def test_the_road_does_drop_away_sometimes(self):
        """The counterpart to the test above: if every feature were tuned out
        the road would be safe and also pointless, and the truck could never
        take enough of a landing to be wrecked."""
        biggest = max(
            b - a
            for seed in range(100)
            for a, b in zip(generate_route(seed).heights, generate_route(seed).heights[1:])
        )
        assert biggest >= 40, "no route drops away sharply enough to launch the rig"

    def test_dimensions_are_whole_numbers(self):
        """Sizes are built from integer units on purpose - see the note in
        generate_route. A fractional one means someone reintroduced a
        rounded float, which is exactly where JavaScript and Python stop
        agreeing."""
        for seed in range(500):
            for crate in generate_route(seed).crates:
                assert crate.w == int(crate.w) and crate.h == int(crate.h)
                assert crate.kind in CRATE_SPANS

    def test_nothing_is_wider_than_the_deck(self):
        """A single item that cannot fit between the headboard and the rear
        lip is unloadable, and the player has no way to tell that the route
        rather than their placement is at fault. The deck runs from -120 to
        +54 of the chassis centre - 174px - and an item may be laid on its
        side, so its shorter span is the one that has to fit."""
        deck = 174
        for seed in range(500):
            for crate in generate_route(seed).crates:
                assert min(crate.w, crate.h) <= deck

    def test_same_seed_is_reproducible(self):
        """The property the entire anti-cheat rests on."""
        first, second = generate_route(777), generate_route(777)
        assert first.heights == second.heights
        assert first.crates == second.crates

    def test_different_seeds_give_different_routes(self):
        routes = {tuple(generate_route(s).heights) for s in range(100)}
        assert len(routes) == 100
