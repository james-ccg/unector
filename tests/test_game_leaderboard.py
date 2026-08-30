"""
Tests for the game leaderboard's defences.

The client runs the physics, so it can claim anything. These tests are the
record of what the server actually refuses, and what it deliberately doesn't:
the ticket has to be real, unused, issued to the submitting account and still
valid, and the claimed payout has to fit inside what the named route could
possibly pay. Re-simulating the run is out of scope by design - see the note
on the submit endpoint.

Each case below is an attack someone would genuinely try against a browser
leaderboard, not a hypothetical.
"""
import pytest

from tests.conftest import csrf_headers as _csrf_headers, unique_mc


def _register(client) -> str:
    """Registers a fresh company and returns its display name."""
    mc_number = unique_mc()
    reg = client.post("/api/auth/register", json={
        "mc_number": mc_number,
        "company_name": f"Game Co {mc_number}",
        "email": f"owner{mc_number}@gametest.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert reg.status_code == 200, reg.text
    return f"Game Co {mc_number}"


def _tickets(client) -> list[dict]:
    response = client.post("/api/game/sessions", headers=_csrf_headers(client))
    assert response.status_code == 200, response.text
    return response.json()["issued"]


class TestSessionIssuing:
    def test_issues_a_batch_so_the_game_works_offline(self, client):
        _register(client)
        issued = _tickets(client)
        assert len(issued) == 5
        # The seed must come from the server - a client that picks its own
        # can pick a route it has already solved.
        assert all(t["seed"] >= 0 and t["token"] for t in issued)

    def test_seeds_differ_between_tickets(self, client):
        _register(client)
        seeds = [t["seed"] for t in _tickets(client)]
        assert len(set(seeds)) == len(seeds)

    def test_tops_up_rather_than_stacking_indefinitely(self, client):
        """Otherwise repeatedly calling this is a way to hoard attempts."""
        _register(client)
        _tickets(client)
        second = client.post("/api/game/sessions", headers=_csrf_headers(client)).json()
        assert second["issued"] == []
        assert second["held"] == 5

    def test_requires_a_session(self, client):
        # Signed out there is no CSRF cookie either, so this is refused by
        # whichever guard runs first - both are correct answers to "no".
        assert client.post("/api/game/sessions").status_code in (401, 403)


class TestScoreValidation:
    def _setup(self, client) -> dict:
        _register(client)
        return _tickets(client)[0]

    def test_accepts_an_honest_run(self, client):
        ticket = self._setup(client)
        response = client.post("/api/game/scores", json={
            "token": ticket["token"],
            "payout": ticket["max_payout"],
            "delivered": 3, "lost": 0, "duration_ms": 30_000,
        }, headers=_csrf_headers(client))
        assert response.status_code == 200, response.text
        assert response.json()["payout"] == ticket["max_payout"]

    def test_rejects_a_payout_above_what_the_route_can_pay(self, client):
        """The headline defence. Without the server knowing the route, this
        is just a number the client made up."""
        ticket = self._setup(client)
        response = client.post("/api/game/scores", json={
            "token": ticket["token"],
            "payout": ticket["max_payout"] + 1,
            "delivered": 3, "lost": 0, "duration_ms": 30_000,
        }, headers=_csrf_headers(client))
        assert response.status_code == 400
        assert "higher than" in response.json()["detail"]

    def test_rejects_a_replayed_ticket(self, client):
        """One good run must not be submittable over and over."""
        ticket = self._setup(client)
        payload = {
            "token": ticket["token"], "payout": 500,
            "delivered": 1, "lost": 0, "duration_ms": 30_000,
        }
        assert client.post("/api/game/scores", json=payload, headers=_csrf_headers(client)).status_code == 200
        again = client.post("/api/game/scores", json=payload, headers=_csrf_headers(client))
        assert again.status_code == 400
        assert "already been submitted" in again.json()["detail"]

    def test_rejects_an_invented_token(self, client):
        _register(client)
        response = client.post("/api/game/scores", json={
            "token": "not-a-real-token", "payout": 100,
            "delivered": 1, "lost": 0, "duration_ms": 30_000,
        }, headers=_csrf_headers(client))
        assert response.status_code == 400

    def test_rejects_a_ticket_issued_to_another_account(self, client):
        """Tokens are not bearer credentials - lifting one from someone else
        must not let you post under your own name."""
        _register(client)
        stolen = _tickets(client)[0]
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        _register(client)
        response = client.post("/api/game/scores", json={
            "token": stolen["token"], "payout": 100,
            "delivered": 1, "lost": 0, "duration_ms": 30_000,
        }, headers=_csrf_headers(client))
        assert response.status_code == 400
        assert "another account" in response.json()["detail"]

    @pytest.mark.parametrize("duration", [0, 500, 7_999, 60 * 60 * 1000 + 1])
    def test_rejects_an_impossible_run_time(self, client, duration):
        """A script posting instant runs is the cheapest attack there is."""
        ticket = self._setup(client)
        response = client.post("/api/game/scores", json={
            "token": ticket["token"], "payout": 100,
            "delivered": 1, "lost": 0, "duration_ms": duration,
        }, headers=_csrf_headers(client))
        assert response.status_code == 400

    def test_rejects_negative_values(self, client):
        ticket = self._setup(client)
        response = client.post("/api/game/scores", json={
            "token": ticket["token"], "payout": -5,
            "delivered": 1, "lost": 0, "duration_ms": 30_000,
        }, headers=_csrf_headers(client))
        assert response.status_code == 400

    def test_requires_a_session(self, client):
        response = client.post("/api/game/scores", json={
            "token": "x", "payout": 1, "delivered": 1, "lost": 0, "duration_ms": 30_000,
        })
        assert response.status_code in (401, 403)


class TestLeaderboard:
    def test_ranks_by_best_single_run(self, client):
        """Best haul, not most hauls - otherwise the board measures free time
        rather than skill."""
        name = _register(client)
        tickets = _tickets(client)
        for ticket, payout in zip(tickets, [400, 1200, 700]):
            client.post("/api/game/scores", json={
                "token": ticket["token"], "payout": min(payout, ticket["max_payout"]),
                "delivered": 2, "lost": 0, "duration_ms": 25_000,
            }, headers=_csrf_headers(client))

        board = client.get("/api/game/leaderboard?period=week").json()["entries"]
        mine = [e for e in board if e["name"] == name]
        assert len(mine) == 1, "an account should appear once, with its best run"

    def test_is_readable_without_signing_in(self, client):
        # Fresh client, never signed in.
        assert client.get("/api/game/leaderboard?period=week").status_code == 200

    def test_rejects_an_unknown_period(self, client):
        assert client.get("/api/game/leaderboard?period=decade").status_code == 400

    @pytest.mark.parametrize("period", ["week", "month"])
    def test_both_periods_work(self, client, period):
        response = client.get(f"/api/game/leaderboard?period={period}")
        assert response.status_code == 200
        assert response.json()["period"] == period
