"""
Every change to a company's records is told about, from one place.

The promise is a broad one - "if anything changes, say so" - and the way it
breaks is not dramatic: somebody adds an endpoint, forgets the notify()
call, and the promise quietly stops being true for exactly the change that
mattered. So the mapping lives in one list and these tests hold two things
against it: that the list says what it means, and that the middleware only
speaks when a request really did change something.
"""
from unittest.mock import patch

import pytest

from services import change_log, notification_events as events
from tests.conftest import csrf_headers, unique_mc


class TestTheMap:
    @pytest.mark.parametrize("method,path,expected", [
        ("POST", "/api/drivers", "fleet.roster_changed"),
        ("DELETE", "/api/drivers/7", "fleet.roster_changed"),
        ("PATCH", "/api/drivers/7/subscription", "fleet.roster_changed"),
        ("PUT", "/api/drivers/7/group", "fleet.group_linked"),
        ("POST", "/api/trucks", "fleet.roster_changed"),
        ("PATCH", "/api/trucks/3", "fleet.roster_changed"),
        ("DELETE", "/api/trailers/3", "fleet.roster_changed"),
        ("POST", "/api/dispatchers", "account.team_changed"),
        ("DELETE", "/api/dispatchers/2", "account.team_changed"),
        ("DELETE", "/api/settings/gmail", "account.settings_changed"),
        ("POST", "/api/settings/alert-rules", "account.settings_changed"),
        ("PATCH", "/api/settings/alert-rules/5", "account.settings_changed"),
        ("DELETE", "/api/billing/payment-methods/pm_123", "billing.payment_method_changed"),
    ])
    def test_a_change_is_matched_to_an_event(self, method, path, expected):
        matched = change_log.match(method, path)
        assert matched is not None, f"{method} {path}"
        assert matched[0] == expected

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/drivers"),
        ("GET", "/api/dispatchers"),
        # Reading a page is not changing it, whatever the verb.
        ("POST", "/api/auth/owner"),
        ("POST", "/api/notifications/read"),
        # Announced from inside the endpoint instead, with detail this map
        # cannot reach - which fields changed, and what the bot managed to
        # write. Matching here too would say it twice.
        ("PATCH", "/api/drivers/7/details"),
        ("POST", "/api/group-profiles/4/confirm"),
        # A circle: the screen that changed it is already showing the answer.
        ("PUT", "/api/notifications/preferences"),
        # Asking Stripe to collect a method is not the same as one arriving.
        ("POST", "/api/billing/payment-methods/setup"),
        ("POST", "/api/billing/checkout"),
    ])
    def test_what_is_deliberately_not_announced(self, method, path):
        assert change_log.match(method, path) is None

    def test_a_trailing_slash_is_the_same_request(self):
        assert change_log.match("POST", "/api/drivers/") == change_log.match("POST", "/api/drivers")

    def test_an_id_that_is_not_an_id_does_not_match_by_accident(self):
        """Ids are spelled out as digits rather than a catch-all, so a path
        this list does not really cover cannot slip through."""
        assert change_log.match("DELETE", "/api/drivers/all") is None
        assert change_log.match("PATCH", "/api/trucks/../secrets") is None

    def test_every_event_the_map_names_actually_exists(self):
        """The map and the catalogue drifting apart would mean notifications
        addressed to an event nobody can switch off or on."""
        for _method, _pattern, key, _title in change_log.RULES:
            assert events.get(key) is not None, key

    def test_every_title_reads_as_a_sentence(self):
        for _method, _pattern, _key, title in change_log.RULES:
            assert title[0].isupper(), title
            assert not title.endswith("."), title


class TestWhoMadeTheChange:
    def test_a_name_is_used_when_the_session_has_one(self):
        assert change_log.actor_name({"username": "dispatch1"}) == "dispatch1"
        assert change_log.actor_name({"email": "owner@example.com"}) == "owner@example.com"

    def test_the_role_stands_in_when_there_is_no_name(self):
        assert change_log.actor_name({"role": "owner"}) == "the owner"

    def test_nothing_usable_means_nothing_is_claimed(self):
        """Better to say what changed and not by whom than to invent one."""
        assert change_log.actor_name({}) is None
        assert change_log.actor_name({"role": "robot"}) is None
        assert change_log.actor_name({"username": "   "}) is None


class TestThroughTheApp:
    def _owner(self, client):
        client.post("/api/auth/register", json={
            "mc_number": unique_mc(),
            "company_name": "Change Log Co",
            "email": f"owner{unique_mc()}@example.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })

    def test_adding_a_driver_is_announced(self, client):
        self._owner(client)
        with patch("services.notification_service.notify") as notify:
            response = client.post(
                "/api/drivers", json={"full_name": "Driver One"}, headers=csrf_headers(client),
            )
        assert response.status_code == 200, response.text
        keys = [call.args[1] for call in notify.call_args_list]
        assert "fleet.roster_changed" in keys

    def test_a_refused_change_is_not_announced(self, client):
        """A 4xx changed nothing. Telling somebody their record was edited
        when it was not is worse than silence."""
        self._owner(client)
        with patch("services.notification_service.notify") as notify:
            response = client.delete("/api/drivers/99999", headers=csrf_headers(client))
        assert response.status_code >= 400
        assert not any(
            call.args[1] == "fleet.roster_changed" for call in notify.call_args_list
        )

    def test_a_signed_out_request_is_not_announced(self, client):
        """No session, no company to tell - and the request was refused
        anyway."""
        with patch("services.notification_service.notify") as notify:
            client.post("/api/drivers", json={"full_name": "Driver One"})
        assert notify.call_args_list == []

    def test_a_notification_that_cannot_be_sent_does_not_break_the_request(self, client):
        """The change is already made and answered for by the time this
        runs, so a failure here must not turn a successful edit into an
        error the caller sees."""
        self._owner(client)
        with patch("services.notification_service.notify", side_effect=RuntimeError("bell is down")):
            response = client.post(
                "/api/drivers", json={"full_name": "Driver One"}, headers=csrf_headers(client),
            )
        assert response.status_code == 200, response.text
