"""
The five two-factor cards, and what their badges say.

They sit in a column and are read down, so a badge that phrases itself
differently from the ones above it reads as a different kind of thing rather
than as the same field with a different value. Security keys was showing a
raw count - "0 registered" - where every other card gives a state, which
looks like a value that failed to load rather than "none yet".

The icons matter for the same reason. A tick on a card with nothing set up
says the opposite of the badge beside it.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = (
    ROOT / "frontend" / "src" / "components" / "TwoFactorSettings.tsx"
).read_text(encoding="utf-8")
ICONS = (ROOT / "frontend" / "src" / "components" / "Icon.tsx").read_text(encoding="utf-8")

CARDS = ["Authenticator app", "Email code", "Text message", "Telegram", "Security keys"]


def _card(title: str) -> str:
    """The header block for one card - icon, title, badge."""
    start = COMPONENT.index(f"<h3>{title}</h3>")
    head = COMPONENT.rindex('<div className="twofa-card-head">', 0, start)
    end = COMPONENT.index("</div>", COMPONENT.index("status-badge", start))
    return COMPONENT[head:end]


class TestEveryCardSaysWhereItStands:
    @pytest.mark.parametrize("title", CARDS)
    def test_it_has_a_badge(self, title):
        assert "status-badge" in _card(title), title

    @pytest.mark.parametrize("title", CARDS)
    def test_the_badge_gives_a_state_when_there_is_nothing_set_up(self, title):
        """Not a count. "0 registered" was the odd one out, and it read as a
        number that had failed to load."""
        card = _card(title)
        assert re.search(r"'(Not enabled|Not linked)'", card), title

    def test_security_keys_still_counts_once_there_are_some(self):
        """The count is worth showing - two keys registered is different from
        one - just not before there is anything to count."""
        card = _card("Security keys")
        assert "registered" in card
        assert "webauthnCreds.length" in card


class TestTheIcons:
    @pytest.mark.parametrize("title,icon", [
        ("Authenticator app", "shield"),
        ("Email code", "email"),
        ("Text message", "phone"),
        ("Telegram", "telegram"),
        ("Security keys", "key"),
    ])
    def test_each_card_wears_its_own(self, title, icon):
        assert f'Icon name="{icon}"' in _card(title), title

    def test_no_card_wears_a_tick(self):
        """A tick says "done". On a card with nothing set up it contradicts
        the badge next to it, which is where this started."""
        for title in CARDS:
            assert 'Icon name="check"' not in _card(title), title

    def test_the_key_icon_exists(self):
        assert re.search(r"^  key: <>", ICONS, re.M)
        assert "'key'" in ICONS
