"""
Where Telegram gets connected, and what the switches do until it is.

Connecting belongs in Integrations, beside Gmail and Samsara: it is a
connection to an outside account, which is what that tab is for. The
notification screen is a separate question - what to send, once somewhere to
send it exists - so it points across rather than doing the connecting.

Until it is connected there is nowhere to deliver to, and that is the state
worth being careful about: a Telegram switch saved while nothing is
connected looks exactly like one that works, and the difference only shows
up as the message nobody received.
"""
import pathlib

import pytest

from db import models, repository
from db.database import get_session
from tests.conftest import csrf_headers, unique_mc

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
INTEGRATION = (FRONTEND / "components" / "TelegramIntegration.tsx").read_text(encoding="utf-8")
NOTIFICATIONS = (FRONTEND / "components" / "NotificationSettings.tsx").read_text(encoding="utf-8")
SETTINGS = (FRONTEND / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")


class TestWhereConnectingLives:
    def test_the_card_is_rendered_in_integrations(self):
        assert "<TelegramIntegration />" in SETTINGS
        # Immediately before the Samsara card, so the three connections sit
        # together rather than one of them being somewhere else.
        assert SETTINGS.index("<TelegramIntegration />") < SETTINGS.index('id="samsara"')

    def test_the_card_carries_the_anchor_the_links_point_at(self):
        assert 'id="telegram"' in INTEGRATION

    def test_the_hash_switches_to_the_right_tab(self):
        """The tabs hide sections rather than unmounting them, so a link to a
        card in another tab scrolls to something behind display:none unless
        the hash map knows which tab holds it."""
        assert "telegram: 'integrations'," in SETTINGS

    def test_notifications_no_longer_does_the_connecting(self):
        """Two places to connect the same thing is two places to keep in
        step, and the one nobody updates is the one somebody uses."""
        assert "startTelegramLink" not in NOTIFICATIONS
        assert "stopTelegramLink" not in NOTIFICATIONS

    def test_notifications_points_at_it_instead(self):
        assert 'href="#telegram"' in NOTIFICATIONS


class TestTheSwitchesAreGated:
    def test_turning_telegram_on_unconnected_is_refused_in_the_ui(self):
        assert "channel === 'telegram' && !telegram.connected" in NOTIFICATIONS
        assert "Connect Telegram in Integrations first" in NOTIFICATIONS

    def test_the_chip_shows_as_unavailable(self):
        """Dimmed rather than hidden: the reader should see that Telegram is
        an option that is not available yet, not wonder why this row has one
        fewer chip than the next."""
        assert "is-unavailable" in NOTIFICATIONS

    def test_it_is_locked_in_both_directions(self):
        """With nothing connected the switch means nothing either way: on
        would save a preference that can never deliver, off would be turning
        off something that was never going to arrive. An earlier version
        gated only the on direction, which left a switch that could be moved
        one way and not back."""
        gate = NOTIFICATIONS[NOTIFICATIONS.index("if (channel === 'telegram'"):]
        gate = gate[:gate.index("}")]
        assert "state.enabled" not in gate, "the gate still checks which way it is moving"

    def test_the_chip_is_not_disabled(self):
        """A disabled button fires no click, so pressing it would explain
        nothing and simply feel broken. It stays pressable and answers."""
        assert "disabled={state.locked || busy === key}" in NOTIFICATIONS

    def test_the_explanation_appears_beside_the_chip(self):
        """It used to be a line at the top of the list, which somebody who
        had scrolled down to a switch never saw."""
        assert "ns-chip-wrap" in NOTIFICATIONS
        assert "ns-hint" in NOTIFICATIONS

    def test_the_explanation_clears_itself(self):
        assert "const HINT_MS = 1000" in NOTIFICATIONS
        assert "setTimeout(() => setHint(null), HINT_MS)" in NOTIFICATIONS

    def test_the_countdown_is_held_while_it_is_being_looked_at(self):
        """A second is not long enough to read a sentence - it is long enough
        to notice one appeared. What makes it work is that the pointer is on
        the chip at the moment of the click, and the countdown is held while
        it stays there: the message lasts as long as somebody is looking at
        it, and goes a second after they look away."""
        assert "onMouseEnter={hint === key ? clearHintTimer : undefined}" in NOTIFICATIONS
        assert "onMouseLeave={hint === key ? startHintTimer : undefined}" in NOTIFICATIONS

    def test_a_keyboard_user_gets_the_same_hold(self):
        """They have no pointer to hold it with, and would otherwise be the
        one person the message flashes past."""
        assert "onFocus={hint === key ? clearHintTimer : undefined}" in NOTIFICATIONS
        assert "onBlur={hint === key ? startHintTimer : undefined}" in NOTIFICATIONS

    def test_the_timer_is_cleared_on_unmount(self):
        """Otherwise it sets state on a component that is gone - a warning in
        the console and a leak on a page somebody opens and closes often."""
        assert "useEffect(() => clearHintTimer, [])" in NOTIFICATIONS

    def test_the_bubble_does_not_move_the_page(self):
        """A row that grew and shrank would shove the rest of the list about
        every time a locked chip was pressed, which reads as glitching."""
        css = (
            ROOT / "frontend" / "src" / "components" / "NotificationSettings.css"
        ).read_text(encoding="utf-8")
        hint = css[css.index(".ns-hint {"):]
        hint = hint[:hint.index("}")]
        assert "position: absolute" in hint


class TestTheServerStillDecides:
    """The gate above is a courtesy - it explains rather than enforces. What
    actually protects delivery is that a notification with nowhere to go is
    skipped, which is server-side and tested here."""

    def _owner(self, client) -> int:
        mc = unique_mc()
        response = client.post("/api/auth/register", json={
            "mc_number": mc,
            "company_name": f"Gate {mc}",
            "email": f"owner{mc}@example.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert response.status_code == 200, response.text
        with get_session() as session:
            return (
                session.query(models.Company)
                .filter(models.Company.mc_number == mc)
                .first().id
            )

    def test_the_preference_can_still_be_saved(self, client):
        """Deliberately allowed. Somebody may turn switches on before
        connecting, and refusing the save would lose a choice they meant to
        make - the screen tells them the order, it does not police it."""
        self._owner(client)
        response = client.put(
            "/api/notifications/preferences",
            json={"event": "load.dispatched", "channel": "telegram", "enabled": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text

    def test_but_nothing_is_sent_with_nowhere_to_send_it(self, client):
        """The part that matters. An unconnected account is skipped by name,
        rather than a send being attempted and failing."""
        from services import notification_service

        company_id = self._owner(client)
        client.put(
            "/api/notifications/preferences",
            json={"event": "load.dispatched", "channel": "telegram", "enabled": True},
            headers=csrf_headers(client),
        )

        result = notification_service.notify(
            company_id, "load.dispatched", title="A load went out",
        )
        assert result["sent"]["telegram"] == 0
        assert any("telegram (not linked)" in s for s in result["skipped"])

    def test_and_is_sent_once_it_is_connected(self, client, monkeypatch):
        from services import notification_service

        company_id = self._owner(client)
        client.put(
            "/api/notifications/preferences",
            json={"event": "load.dispatched", "channel": "telegram", "enabled": True},
            headers=csrf_headers(client),
        )
        repository.link_telegram_account("owner", company_id, 993001, "someone")

        sent = []
        monkeypatch.setattr(
            notification_service, "_deliver_telegram",
            lambda target, title, body: sent.append(target),
        )
        result = notification_service.notify(
            company_id, "load.dispatched", title="A load went out",
        )
        assert sent == [993001]
        assert result["sent"]["telegram"] == 1
