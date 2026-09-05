"""Every change to a company's records, told once, from one place.

The ask this answers is a broad one - "if anything changes, say so" - and
the tempting way to build it is a notify() call at the end of each endpoint
that writes something. That version is wrong within a month: the next
endpoint somebody adds does not have the call, nobody notices, and the
promise quietly stops being true for exactly the change that mattered.

So this is a map instead, read by one middleware after the response is
built. A new endpoint is covered by adding a line here, and an endpoint
nobody adds a line for is at least visibly absent from a single list rather
than invisibly absent from twenty functions.

Guidance on audit trails asks for four things - who, what, when, and which
record - and the notification carries all four: the actor comes from the
session, the action and the record from the map below, and the timestamp
from the row itself. Guidance on notification fatigue asks for the opposite
restraint, which is why almost everything here defaults to the dashboard
alone: the site feed is the record, and Telegram and email are for the
carrier who asks for them (see services/notification_events.py).

Two kinds of change are deliberately not here:

* Ones already announced with detail the map cannot reach. Editing a
  driver's details says which fields changed, and the bot's own writes say
  which of the name, description and logo it managed - both from inside the
  endpoint, where that is known.
* Changing the notification settings themselves. A message telling you that
  you changed which messages you get is a circle, and the screen that sent
  it is already showing the answer.
"""
from __future__ import annotations

import re

# (method, path pattern) -> (event key, what to say)
#
# Patterns are matched whole against the request path. Ids are written as
# \d+ rather than a catch-all so that a path this list does not really cover
# cannot match by accident.
_ID = r"\d+"

RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    # ---- the fleet list itself ----
    ("POST", re.compile(r"/api/drivers"), "fleet.roster_changed", "A driver was added"),
    ("DELETE", re.compile(rf"/api/drivers/{_ID}"), "fleet.roster_changed", "A driver was removed"),
    (
        "PATCH", re.compile(rf"/api/drivers/{_ID}/subscription"),
        "fleet.roster_changed", "A driver was activated or paused",
    ),
    ("POST", re.compile(r"/api/trucks"), "fleet.roster_changed", "A truck was added"),
    (
        "PATCH", re.compile(rf"/api/trucks/{_ID}"),
        "fleet.roster_changed", "A truck's driver or trailer changed",
    ),
    ("DELETE", re.compile(rf"/api/trucks/{_ID}"), "fleet.roster_changed", "A truck was removed"),
    ("POST", re.compile(r"/api/trailers"), "fleet.roster_changed", "A trailer was added"),
    (
        "DELETE", re.compile(rf"/api/trailers/{_ID}"),
        "fleet.roster_changed", "A trailer was removed",
    ),

    # ---- which group a driver's loads go to ----
    (
        "PUT", re.compile(rf"/api/drivers/{_ID}/group"),
        "fleet.group_linked", "A driver's Telegram group was changed",
    ),

    # ---- who can get in ----
    ("POST", re.compile(r"/api/dispatchers"), "account.team_changed", "A dispatcher was added"),
    (
        "PATCH", re.compile(rf"/api/dispatchers/{_ID}"),
        "account.team_changed", "A dispatcher's account was changed",
    ),
    (
        "DELETE", re.compile(rf"/api/dispatchers/{_ID}"),
        "account.team_changed", "A dispatcher was removed",
    ),

    # ---- settings and integrations ----
    (
        "DELETE", re.compile(r"/api/settings/gmail"),
        "account.settings_changed", "Gmail was disconnected",
    ),
    (
        "POST", re.compile(r"/api/settings/samsara"),
        "account.settings_changed", "Samsara was connected",
    ),
    (
        "DELETE", re.compile(r"/api/settings/samsara"),
        "account.settings_changed", "Samsara was disconnected",
    ),
    (
        "POST", re.compile(r"/api/settings/alert-rules"),
        "account.settings_changed", "A GPS alert rule was added",
    ),
    (
        "PATCH", re.compile(rf"/api/settings/alert-rules/{_ID}"),
        "account.settings_changed", "A GPS alert rule was edited",
    ),
    (
        "DELETE", re.compile(rf"/api/settings/alert-rules/{_ID}"),
        "account.settings_changed", "A GPS alert rule was removed",
    ),

    # ---- money ----
    #
    # Only the removal. A method is *added* over on Stripe's side, and the
    # webhook is what finds out it worked - announcing it here would be
    # announcing that we asked, which is not the same thing.
    (
        "DELETE", re.compile(rf"/api/billing/payment-methods/[^/]+"),
        "billing.payment_method_changed", "A payment method was removed",
    ),
)

# Where a notification sends the reader to look. Keyed by the first segment
# of the event key, since that is already how the catalogue is grouped.
_LINKS = {
    "fleet": "/settings",
    "account": "/settings",
    "billing": "/settings",
}


def match(method: str, path: str) -> tuple[str, str, str] | None:
    """The event key, title and link for a request, or None to stay quiet.

    Trailing slashes are ignored, because a client that sends one is asking
    for the same thing as one that does not.
    """
    path = path.rstrip("/") or "/"
    method = method.upper()
    for rule_method, pattern, event_key, title in RULES:
        if rule_method == method and pattern.fullmatch(path):
            return event_key, title, _LINKS.get(event_key.split(".", 1)[0], "/dashboard")
    return None


def actor_name(claims: dict) -> str | None:
    """Who made the change, for the notification body.

    "who" is the first thing anyone asks about a change they did not make,
    and it is the one part of it the map cannot know. Returns None rather
    than guessing when the session carries nothing usable, in which case the
    notification simply says what changed and not by whom.
    """
    if not claims:
        return None
    for key in ("username", "email", "name"):
        value = (claims.get(key) or "").strip() if isinstance(claims.get(key), str) else ""
        if value:
            return value
    role = claims.get("role")
    return f"the {role}" if role in ("owner", "dispatcher") else None
