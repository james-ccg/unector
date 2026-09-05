"""
Recovery codes come after a second factor, not before it.

They exist for one situation: the second factor is unavailable and you still
need to get in. With no second factor turned on there is no such situation -
the password alone already signs you in - so codes generated then do nothing
except sit there being one more secret that can be found, written down, or
left in a screenshot.

The rule is enforced on the server as well as hidden in the screen, because
a rule that lives only in the frontend is a suggestion.
"""
import pathlib

import pytest

from db import models, repository
from db.database import get_session
from tests.conftest import csrf_headers, unique_mc

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = (
    ROOT / "frontend" / "src" / "components" / "TwoFactorSettings.tsx"
).read_text(encoding="utf-8")


def _owner(client) -> int:
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Recovery {mc}",
        "email": f"owner{mc}@example.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert response.status_code == 200, response.text
    with get_session() as session:
        return (
            session.query(models.Company).filter(models.Company.mc_number == mc).first().id
        )


def _generate(client):
    return client.post("/api/2fa/recovery-codes/generate", headers=csrf_headers(client))


class TestBeforeAnySecondFactor:
    def test_generating_is_refused(self, client):
        _owner(client)
        response = _generate(client)
        assert response.status_code == 409, response.text

    def test_the_refusal_says_why_rather_than_just_no(self, client):
        """The reader has done nothing wrong and the fix is one screen away,
        so the message names both."""
        _owner(client)
        detail = _generate(client).json()["detail"]
        assert "second factor" in detail
        assert "turn one on first" in detail

    def test_nothing_is_stored(self, client):
        """A refusal that still wrote the codes would be the worst of both -
        unusable secrets, created anyway."""
        company_id = _owner(client)
        _generate(client)
        assert repository.get_2fa_status("owner", company_id)["recovery_codes_remaining"] == 0


class TestOnceThereIsOne:
    def test_generating_works(self, client):
        company_id = _owner(client)
        repository.set_telegram_otp("owner", company_id, 995001, enabled=True)

        response = _generate(client)
        assert response.status_code == 200, response.text
        assert len(response.json()["codes"]) > 0

    def test_the_codes_are_counted(self, client):
        company_id = _owner(client)
        repository.set_telegram_otp("owner", company_id, 995002, enabled=True)
        issued = _generate(client).json()["codes"]

        remaining = repository.get_2fa_status("owner", company_id)["recovery_codes_remaining"]
        assert remaining == len(issued)

    def test_generating_again_replaces_them(self, client):
        """Not adds to them. Somebody regenerating has lost the old set or
        thinks it leaked, and leaving the old ones valid would defeat both
        reasons for pressing the button."""
        company_id = _owner(client)
        repository.set_telegram_otp("owner", company_id, 995003, enabled=True)

        first = set(_generate(client).json()["codes"])
        second = set(_generate(client).json()["codes"])
        assert first != second
        assert repository.get_2fa_status("owner", company_id)["recovery_codes_remaining"] == len(second)

    def test_codes_survive_the_factor_being_turned_off(self, client):
        """Deliberately kept. Deleting somebody's recovery codes because they
        switched a method off would be a destructive surprise, and they are
        unusable while no factor is on anyway - login never asks."""
        company_id = _owner(client)
        repository.set_telegram_otp("owner", company_id, 995004, enabled=True)
        _generate(client)

        repository.set_telegram_otp("owner", company_id, 995004, enabled=False)
        status = repository.get_2fa_status("owner", company_id)
        assert status["any_enabled"] is False
        assert status["recovery_codes_remaining"] > 0


class TestTheScreenAgrees:
    def test_the_card_is_hidden_until_a_factor_is_on(self):
        assert "{status?.any_enabled && (" in COMPONENT

    def test_it_is_the_recovery_card_that_is_gated(self):
        """Guards the gate itself: a later edit moving the conditional onto
        a different card would leave this passing while the wrong thing is
        hidden."""
        gate = COMPONENT.index("{status?.any_enabled && (")
        heading = COMPONENT.index("<h3>Recovery codes</h3>")
        between = COMPONENT[gate:heading]
        assert "<h3>" not in between, "another card sits between the gate and the recovery codes"
