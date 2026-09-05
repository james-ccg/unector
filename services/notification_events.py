"""Everything the app can tell somebody about, declared once.

The preference screen, the delivery service, the API and the tests all have
to agree on what events exist, who they are for, and where they go when
nobody has said otherwise. The only way that stays true is if there is one
list, so this is data rather than logic.

Two decisions are baked in.

**Some events cannot be switched off.** Guidance on notification design is
consistent that anything with a real consequence attached - a payment about
to be taken, a failed charge, a sign-in nobody recognises, an integration
that has quietly stopped working - belongs outside the preference system,
because whoever silenced it a year ago will not remember doing so on the
day it matters. Those are `mandatory`, and the settings screen still lists
them, shown as always on: people should be able to see what they will be
told about even when they cannot change it.

**The driver's group is not here.** Load dispatches and GPS proximity
alerts already go to the truck's own Telegram group from bot.py, and that
is dispatch doing its job rather than a notification anyone should be able
to mute. This list is the other direction - telling the office something
happened.
"""
from __future__ import annotations

from dataclasses import dataclass

# Where a notification can land.
#
# "site" is the bell in the dashboard. It is always on and cannot be turned
# off: an email address can be wrong or missing, and Telegram refuses to let
# a bot message anyone who has not started a chat with it first, so the site
# is the one channel that always arrives and the record of what was sent.
SITE = "site"
TELEGRAM = "telegram"
EMAIL = "email"
CHANNELS = (SITE, TELEGRAM, EMAIL)

CHANNEL_LABELS = {
    SITE: "In the dashboard",
    TELEGRAM: "Telegram",
    EMAIL: "Email",
}

# Which login a notification is addressed to. Mirrors the account_type pair
# 2FA and the link tokens already use, so an owner and a dispatcher at the
# same company can be told different things.
OWNER = "owner"
DISPATCHER = "dispatcher"
EVERYONE = (OWNER, DISPATCHER)
OWNER_ONLY = (OWNER,)

CATEGORIES = ("loads", "fleet", "account", "billing", "security")
CATEGORY_LABELS = {
    "loads": "Loads",
    "fleet": "Drivers and trucks",
    "account": "Changes and edits",
    "billing": "Billing",
    "security": "Security and access",
}


@dataclass(frozen=True)
class Event:
    key: str
    category: str
    label: str
    description: str
    # Channels this event may ever use. Narrower than CHANNELS where a
    # channel would be wrong for the content rather than merely unwanted.
    channels: tuple[str, ...]
    # Of those, the ones that are on until somebody says otherwise. Kept
    # modest: an account that emails about everything from day one teaches
    # people to filter the sender into a folder, and then the one message
    # that mattered goes there too.
    defaults: tuple[str, ...]
    audience: tuple[str, ...] = EVERYONE
    mandatory: bool = False

    def allows(self, channel: str) -> bool:
        return channel in self.channels

    def default_for(self, channel: str) -> bool:
        return channel in self.defaults


EVENTS: tuple[Event, ...] = (
    # ------------------------------------------------------------------
    # Loads
    # ------------------------------------------------------------------
    Event(
        key="load.dispatched",
        category="loads",
        label="A load is dispatched",
        description="A rate confirmation was read and sent to the driver's group.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="load.status_changed",
        category="loads",
        label="A driver moves a load along",
        description="Picked up, delivered, or a POD came in.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="load.detention",
        category="loads",
        label="Detention or layover is requested",
        description="A driver has been sitting long enough to bill for it.",
        channels=CHANNELS,
        defaults=(SITE, TELEGRAM),
    ),
    # ------------------------------------------------------------------
    # Drivers and trucks
    # ------------------------------------------------------------------
    Event(
        key="fleet.group_linked",
        category="fleet",
        label="A driver's group is linked",
        description="Someone finished linking a truck's Telegram group.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="fleet.profile_pending",
        category="fleet",
        label="A group description needs checking",
        description=(
            "The bot read truck and driver details out of a group's description "
            "and is waiting for someone to confirm them."
        ),
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="fleet.group_updated",
        category="fleet",
        label="The bot changes a group",
        description=(
            "After a confirmation, the bot writes the group's name, description "
            "and the company logo. This says what it changed."
        ),
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="fleet.details_changed",
        category="fleet",
        label="Truck or driver details change",
        description="Somebody edited a unit number, a name, a phone or a VIN.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="fleet.roster_changed",
        category="fleet",
        label="A driver, truck or trailer is added or removed",
        description="The fleet list itself changed, rather than a detail on it.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    # ------------------------------------------------------------------
    # Changes and edits - the record of what was altered, and by whom
    #
    # These exist because "who changed this?" is a question that gets asked
    # after the fact, and the site feed is the answer. Guidance on audit
    # trails is consistent about the four things worth recording - who, what,
    # when, and to which record - and consistent that the record should be
    # written whether or not anyone is being notified. So the site channel
    # keeps them all; Telegram and email are off until asked for, because a
    # message per edit is how a carrier learns to ignore the sender.
    # ------------------------------------------------------------------
    Event(
        key="account.settings_changed",
        category="account",
        label="Settings change",
        description="An alert rule was edited, or an integration connected or disconnected.",
        channels=CHANNELS,
        defaults=(SITE,),
    ),
    Event(
        key="account.team_changed",
        category="account",
        label="Someone joins or leaves the team",
        description=(
            "A dispatcher was added, renamed or removed. This one defaults to "
            "email as well, because it changes who can get in."
        ),
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        audience=OWNER_ONLY,
    ),
    # ------------------------------------------------------------------
    # Billing - the company's business, and mostly not optional
    #
    # A company has one plan. The owner and every dispatcher share it, and
    # any of them can be the one who paid for it, so all of them hear about
    # it - a dispatcher who arrives to find the account paused should not
    # have to work that out from the driver cap. They can already see the
    # plan and start a checkout, so this exposes nothing new.
    # ------------------------------------------------------------------
    Event(
        key="billing.trial_ending",
        category="billing",
        label="A trial is about to end",
        description="Two days before the first payment is taken.",
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        audience=EVERYONE,
        mandatory=True,
    ),
    Event(
        key="billing.payment_failed",
        category="billing",
        label="A payment failed",
        description="The plan lapses if this is not put right.",
        channels=CHANNELS,
        defaults=(SITE, EMAIL, TELEGRAM),
        audience=EVERYONE,
        mandatory=True,
    ),
    Event(
        key="billing.payment_method_changed",
        category="billing",
        label="A payment method is added or removed",
        description=(
            "Email as well as the dashboard: a method disappearing is how a plan "
            "quietly stops renewing, and the owner should hear about it either way."
        ),
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        audience=EVERYONE,
    ),
    Event(
        key="billing.plan_changed",
        category="billing",
        label="The plan changes",
        description="Upgraded, downgraded, or cancelled.",
        channels=CHANNELS,
        defaults=(SITE,),
        audience=EVERYONE,
    ),
    # ------------------------------------------------------------------
    # Security and access - none of it optional
    # ------------------------------------------------------------------
    Event(
        key="security.new_login",
        category="security",
        label="A new sign-in",
        description="Somebody signed in to this account.",
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        mandatory=True,
    ),
    Event(
        key="security.password_changed",
        category="security",
        label="A password changes",
        description="An account password was reset or changed.",
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        mandatory=True,
    ),
    Event(
        key="security.integration_lost",
        category="security",
        label="An integration stops working",
        description=(
            "Gmail or Samsara disconnected. Dispatch quietly stops working until "
            "it is reconnected, which is why this one cannot be muted."
        ),
        channels=CHANNELS,
        defaults=(SITE, EMAIL),
        mandatory=True,
    ),
)

BY_KEY = {event.key: event for event in EVENTS}


def get(key: str) -> Event | None:
    return BY_KEY.get(key)


def for_audience(audience: str) -> tuple[Event, ...]:
    """The events a given kind of login is ever told about."""
    return tuple(event for event in EVENTS if audience in event.audience)
