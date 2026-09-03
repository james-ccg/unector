"""What a trial that turns into a charge has to say, enforced.

A free trial that converts to a paid, recurring plan is a negative-option
offer. The FTC's 2024 Negative Option Rule was vacated by the Eighth
Circuit in July 2025, but the requirements it restated did not go away:
ROSCA still obliges a seller to disclose the material terms clearly and
conspicuously before taking billing details, and state auto-renewal
laws - California's Business and Professions Code 17600-17606 being the
strictest - want the same terms plus a plain way to cancel.

Those material terms are four: that it renews by itself, when, how much,
and how to stop it. This project adds a fifth of its own, because the code
enforces it: while a plan or trial is live, the last card on file cannot be
removed.

None of that is worth stating once. Copy gets rewritten, and the sentence
that goes missing in a redesign is always the inconvenient one - so the
surfaces that mention a trial are pinned here, and the two lists that have
to agree about which statuses are "live" are checked against each other.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
STRIPE_SERVICE = ROOT / "services" / "stripe_service.py"
BILLING_LIB = FRONTEND / "lib" / "billing.ts"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# The two lists that decide whether a card is held
# ------------------------------------------------------------------

def test_the_front_end_and_the_server_agree_on_what_live_means():
    """The server refuses the removal; the dashboard greys out the button.

    They read from separate lists, so this is the one thing that can drift:
    a status added to the guard but not to the UI means a button that looks
    usable and is not."""
    server = read(STRIPE_SERVICE)
    # Scoped to detach_payment_method on purpose. There is a second
    # live-status list guarding checkout, and it deliberately differs - it
    # counts "incomplete" too, because a half-finished checkout still holds
    # a Stripe object. Only this one decides whether a card can come off.
    start = server.index("def detach_payment_method(")
    end = server.index(chr(10) + "def ", start)
    body = server[start:end]
    guard = re.search(r'subscription_status"\]\s+in\s+\(([^)]*)\)', body, re.DOTALL)
    assert guard, "couldn't find the live-status guard in detach_payment_method"
    server_statuses = set(re.findall(r'"([a-z_]+)"', guard.group(1)))

    client = read(BILLING_LIB)
    listed = re.search(
        r"LIVE_SUBSCRIPTION_STATUSES\s*=\s*\[([^\]]*)\]", client, re.DOTALL
    )
    assert listed, "couldn't find LIVE_SUBSCRIPTION_STATUSES in the billing lib"
    client_statuses = set(re.findall(r"'([a-z_]+)'", listed.group(1)))

    assert server_statuses == client_statuses, (
        f"server says {sorted(server_statuses)}, dashboard says {sorted(client_statuses)}"
    )


def test_the_trial_length_the_pages_quote_is_the_one_stripe_is_given():
    """Seven days is written into the copy in several places. If the
    subscription is ever created with a different number, the pages are
    lying rather than merely out of date."""
    server = read(STRIPE_SERVICE)
    match = re.search(r'trial_period_days"?\]?\s*=\s*(\d+)', server)
    assert match, "couldn't find trial_period_days"
    days = int(match.group(1))

    lib = read(BILLING_LIB)
    assert f"TRIAL_DAYS = {days}" in lib

    for page in ("PricingPage.tsx", "FAQPage.tsx", "TermsOfServicePage.tsx"):
        text = read(FRONTEND / "pages" / page)
        assert f"{days}-day" in text or f"{days} days" in text, (
            f"{page} does not quote the {days}-day trial"
        )


# ------------------------------------------------------------------
# The disclosure itself
# ------------------------------------------------------------------

CONVERSION_PHRASES = ("renews by itself", "renew", "charged automatically", "automatically converts")


@pytest.mark.parametrize("page", ["PricingPage.tsx", "FAQPage.tsx", "TermsOfServicePage.tsx"])
def test_every_page_that_sells_the_trial_also_says_it_converts(page):
    """Naming the free part without the paid part is the half-truth these
    rules exist to stop."""
    text = read(FRONTEND / "pages" / page)
    assert "trial" in text.lower()
    assert any(p in text for p in CONVERSION_PHRASES), (
        f"{page} mentions the trial but never says it turns into a charge"
    )


@pytest.mark.parametrize("page", ["PricingPage.tsx", "FAQPage.tsx", "TermsOfServicePage.tsx"])
def test_every_page_that_sells_the_trial_says_the_card_is_held(page):
    text = read(FRONTEND / "pages" / page)
    collapsed = " ".join(text.split())
    assert any(p in collapsed for p in ("can't be removed", "cannot be removed", "can&apos;t be removed")), (
        f"{page} does not say the last card is held while a plan runs"
    )


def test_the_pricing_page_says_how_to_cancel():
    """A disclosure that does not say how to get out is not a disclosure."""
    collapsed = " ".join(read(FRONTEND / "pages" / "PricingPage.tsx").split())
    assert "Cancel" in collapsed
    assert "Manage billing" in collapsed


def test_the_settings_trial_notice_names_the_amount_and_the_date():
    """On the page where the card actually sits, vagueness is worst."""
    text = read(FRONTEND / "pages" / "SettingsPage.tsx")
    assert "chargeLabel(" in text, "the trial notice does not state what will be charged"
    assert "trial_ends_at" in text, "the trial notice does not state when"


def test_the_remove_button_is_disabled_rather_than_failing():
    """Finding out from a server error is worse than being told first."""
    text = read(FRONTEND / "pages" / "SettingsPage.tsx")
    assert "cardIsHeld" in text
    assert "disabled={cardBusy || cardIsHeld}" in text


def test_the_bot_faq_carries_the_same_terms():
    """Plenty of owners only ever see the bot. The terms travel with it."""
    collapsed = " ".join(read(ROOT / "bot.py").split())
    assert "7-day free trial" in collapsed
    assert "renews by itself" in collapsed
    assert "cannot be removed" in collapsed


def test_nothing_still_promises_the_card_can_come_off_whenever():
    """The old Settings copy said a card could be removed whenever you
    liked. That stopped being true the moment a plan could hold one."""
    for page in FRONTEND.rglob("*.tsx"):
        collapsed = " ".join(read(page).split())
        assert "remove it whenever you like" not in collapsed, page.name
