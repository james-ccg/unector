"""Telling the office something happened, and letting them choose how.

Three rules carry most of the weight here, and each one is a thing that
would be easy to break without noticing:

  * The site channel always fires. Email can bounce and Telegram refuses to
    let a bot message anyone who has not started a chat with it, so the bell
    is the only channel that always arrives - and therefore the record.
  * Mandatory events ignore preferences. A failed payment or an unexpected
    sign-in has a real consequence, and being unwanted is the point.
  * A notification must never break what caused it. A load was dispatched
    whether or not the email went out.
"""
from unittest.mock import patch

import pytest

from db import models, repository
from db.database import get_session
from services import notification_events as events
from services import notification_service as service
from tests.conftest import csrf_headers, unique_mc


@pytest.fixture
def company(request):
    tag = f"NT{abs(hash(request.node.name)) % 100000}"
    with get_session() as session:
        row = models.Company(
            mc_number=f"MC-{tag}",
            company_name=f"Carrier {tag}",
            telegram_group_prefix=tag,
            email=f"owner-{tag}@example.com",
        )
        session.add(row)
        session.commit()
        return row.id


# ------------------------------------------------------------------
# The catalogue
# ------------------------------------------------------------------

def test_every_event_has_a_key_of_its_own():
    keys = [event.key for event in events.EVENTS]
    assert len(keys) == len(set(keys))


def test_every_default_is_a_channel_the_event_allows():
    """A default the event does not permit would be silently dropped, which
    reads as a bug in delivery rather than in the catalogue."""
    for event in events.EVENTS:
        assert set(event.defaults) <= set(event.channels), event.key
        assert set(event.channels) <= set(events.CHANNELS), event.key


def test_every_event_lands_in_a_known_category():
    for event in events.EVENTS:
        assert event.category in events.CATEGORIES, event.key
        assert event.category in events.CATEGORY_LABELS


def test_every_event_reaches_somebody():
    for event in events.EVENTS:
        assert event.audience, event.key
        assert set(event.audience) <= set(events.EVERYONE), event.key


def test_the_site_is_a_default_everywhere():
    """It is the record of what was sent. An event that skipped it would be
    delivered with nothing to look back at."""
    for event in events.EVENTS:
        assert events.SITE in event.defaults, event.key


def test_money_and_access_events_cannot_be_switched_off():
    for event in events.EVENTS:
        if event.category in ("billing", "security"):
            assert event.mandatory or event.key == "billing.plan_changed", event.key


# ------------------------------------------------------------------
# Whether someone gets it
# ------------------------------------------------------------------

def test_an_untouched_switch_follows_the_events_default():
    quiet = events.get("load.dispatched")
    assert service.wants("owner", 999001, quiet, events.SITE) is True
    assert service.wants("owner", 999001, quiet, events.EMAIL) is False


def test_a_saved_choice_wins_over_the_default():
    event = events.get("load.dispatched")
    repository.set_notification_preference("owner", 999002, event.key, events.EMAIL, True)
    assert service.wants("owner", 999002, event, events.EMAIL) is True

    repository.set_notification_preference("owner", 999002, event.key, events.EMAIL, False)
    assert service.wants("owner", 999002, event, events.EMAIL) is False


def test_a_mandatory_event_ignores_a_saved_no():
    """Somebody can write the row - nothing stops that - and it still has to
    have no effect."""
    event = events.get("billing.payment_failed")
    repository.set_notification_preference("owner", 999003, event.key, events.EMAIL, False)
    assert service.wants("owner", 999003, event, events.EMAIL) is True


def test_the_site_channel_ignores_a_saved_no_as_well():
    event = events.get("load.dispatched")
    repository.set_notification_preference("owner", 999004, event.key, events.SITE, False)
    assert service.wants("owner", 999004, event, events.SITE) is True


# ------------------------------------------------------------------
# Sending
# ------------------------------------------------------------------

def test_the_owner_gets_a_record_even_with_no_other_channel(company):
    with patch.object(service, "_deliver_telegram") as telegram:
        result = service.notify(company, "load.dispatched", title="Load #1 sent")

    telegram.assert_not_called()
    assert result["sent"]["site"] == 1

    inbox = repository.list_notifications("owner", company)
    assert [n["title"] for n in inbox] == ["Load #1 sent"]


def test_billing_news_skips_the_dispatchers(company):
    with get_session() as session:
        session.add(models.Dispatcher(
            company_id=company, username="d1", password_hash="x",
        ))
        session.commit()

    service.notify(company, "billing.plan_changed", title="Now on Pro",
                   account_types=("owner",))

    assert repository.unread_notification_count("owner", company) == 1
    with get_session() as session:
        dispatcher = session.query(models.Dispatcher).filter_by(company_id=company).first()
    assert repository.unread_notification_count("dispatcher", dispatcher.id) == 0


def test_a_channel_that_fails_does_not_stop_the_others(company):
    """The load still got dispatched. Losing the email is a smaller problem
    than an SMTP timeout taking the dispatch with it."""
    repository.set_notification_preference(
        "owner", company, "load.detention", events.EMAIL, True
    )
    with patch.object(service, "_deliver_telegram", side_effect=RuntimeError("HTTP 403")), \
         patch("services.email_otp_service.send_notification_email",
               side_effect=OSError("connection refused")):
        result = service.notify(company, "load.detention", title="Detention on #7")

    assert result["sent"]["site"] == 1
    assert result["sent"]["telegram"] == 0
    assert result["sent"]["email"] == 0
    assert repository.unread_notification_count("owner", company) == 1


def test_an_unknown_event_is_refused_rather_than_sent(company):
    with pytest.raises(ValueError, match="No such notification event"):
        service.notify(company, "load.teleported", title="?")


def test_telegram_is_skipped_when_nobody_has_linked_an_account(company):
    repository.set_notification_preference(
        "owner", company, "load.dispatched", events.TELEGRAM, True
    )
    with patch.object(service, "_deliver_telegram") as telegram:
        result = service.notify(company, "load.dispatched", title="Load #2 sent")

    telegram.assert_not_called()
    assert any("not linked" in note for note in result["skipped"])


# ------------------------------------------------------------------
# The API
# ------------------------------------------------------------------

@pytest.fixture
def owner(client):
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Notify Co {mc}",
        "email": f"owner{mc}@example.com",
        "password": "correcthorse123",
        "confirm_password": "correcthorse123",
    })
    assert response.status_code == 200, response.text
    with get_session() as session:
        company_id = session.query(models.Company).filter_by(mc_number=mc).first().id
    return {"client": client, "company_id": company_id}


def test_the_bell_starts_empty_and_counts_what_arrives(owner):
    client = owner["client"]
    assert client.get("/api/notifications").json() == {"notifications": [], "unread": 0}

    service.notify(owner["company_id"], "load.dispatched", title="Load #3 sent",
                   body="To Test Driver", link="/dashboard")

    payload = client.get("/api/notifications").json()
    assert payload["unread"] == 1
    assert payload["notifications"][0]["title"] == "Load #3 sent"
    assert payload["notifications"][0]["link"] == "/dashboard"
    assert payload["notifications"][0]["read"] is False


def test_marking_them_read_empties_the_count(owner):
    client = owner["client"]
    service.notify(owner["company_id"], "load.dispatched", title="Load #4 sent")

    response = client.post("/api/notifications/read", json={}, headers=csrf_headers(client))
    assert response.status_code == 200
    assert response.json()["unread"] == 0
    assert client.get("/api/notifications").json()["notifications"][0]["read"] is True


def test_signing_in_is_required_to_see_them(client):
    assert client.get("/api/notifications").status_code == 401


def test_the_preferences_screen_describes_the_whole_catalogue(owner):
    payload = owner["client"].get("/api/notifications/preferences").json()

    assert [c["key"] for c in payload["channels"]] == list(events.CHANNELS)
    keys = {row["event"] for row in payload["events"]}
    assert keys == {e.key for e in events.for_audience("owner")}

    row = next(r for r in payload["events"] if r["event"] == "load.dispatched")
    assert row["channels"]["site"]["enabled"] is True
    assert row["channels"]["site"]["locked"] is True
    assert row["channels"]["email"]["enabled"] is False
    assert row["channels"]["email"]["locked"] is False


def test_mandatory_events_are_shown_but_locked(owner):
    payload = owner["client"].get("/api/notifications/preferences").json()
    row = next(r for r in payload["events"] if r["event"] == "billing.payment_failed")
    assert row["mandatory"] is True
    assert all(channel["locked"] for channel in row["channels"].values())


def test_a_switch_can_be_moved_and_comes_back_moved(owner):
    client = owner["client"]
    response = client.put(
        "/api/notifications/preferences",
        json={"event": "load.dispatched", "channel": "email", "enabled": True},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200

    payload = client.get("/api/notifications/preferences").json()
    row = next(r for r in payload["events"] if r["event"] == "load.dispatched")
    assert row["channels"]["email"]["enabled"] is True


def test_a_mandatory_event_refuses_to_be_switched_off(owner):
    client = owner["client"]
    response = client.put(
        "/api/notifications/preferences",
        json={"event": "billing.payment_failed", "channel": "email", "enabled": False},
        headers=csrf_headers(client),
    )
    assert response.status_code == 409
    assert "can't be turned off" in response.json()["detail"]


def test_the_site_channel_refuses_to_be_switched_off(owner):
    client = owner["client"]
    response = client.put(
        "/api/notifications/preferences",
        json={"event": "load.dispatched", "channel": "site", "enabled": False},
        headers=csrf_headers(client),
    )
    assert response.status_code == 409


def test_an_unknown_event_or_channel_is_named_in_the_error(owner):
    client = owner["client"]
    unknown = client.put(
        "/api/notifications/preferences",
        json={"event": "load.teleported", "channel": "email", "enabled": True},
        headers=csrf_headers(client),
    )
    assert unknown.status_code == 404
    assert "load.teleported" in unknown.json()["detail"]

    channel = client.put(
        "/api/notifications/preferences",
        json={"event": "load.dispatched", "channel": "carrier_pigeon", "enabled": True},
        headers=csrf_headers(client),
    )
    assert channel.status_code == 400
    assert "carrier_pigeon" in channel.json()["detail"]


def test_changing_a_preference_needs_the_csrf_header(owner):
    response = owner["client"].put(
        "/api/notifications/preferences",
        json={"event": "load.dispatched", "channel": "email", "enabled": True},
    )
    assert response.status_code == 403
