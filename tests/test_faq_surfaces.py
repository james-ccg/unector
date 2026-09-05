"""
The FAQ exists twice, and the site's is the complete one.

`/faq` in Telegram carries the questions somebody asks from inside Telegram
- what this is, how to wire up a truck's group, and what it costs - and
points at /pages/faq for the rest. The site's answers everything.

That division is the thing worth holding still. Two full copies drifted
almost immediately when they existed: the site gained the trial-reminder
email and the bot did not, and neither mentioned the group features for two
days after they shipped. A short copy that links to the long one only fails
one way, and this file is that check - that the bot still covers the
essentials, that the site covers everything, and that the bot's pointer to
the site is actually there.

Wording is not checked; the two are allowed to read differently. Subjects
are.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")
PAGE = (ROOT / "frontend" / "src" / "pages" / "FAQPage.tsx").read_text(encoding="utf-8")


# Imported rather than sliced out of the source: the text outgrew Telegram's
# message limit and now lives in a constant that is split on the way out, so
# it is no longer inside the handler to slice.
from bot import FAQ_TEXT as BOT_FAQ  # noqa: E402


# Each subject, and a word or phrase an answer about it cannot avoid.
# Deliberately loose - the nouns the subject cannot be discussed without,
# not the sentences we happen to use today.
#
# ESSENTIALS are the ones somebody asks from inside Telegram, so both copies
# carry them. The trial is here for a reason beyond usefulness: a free trial
# that turns into a charge is a negative-option offer, and ROSCA wants the
# material terms given clearly before billing details are taken. Plenty of
# owners only ever see the bot, so "it is on the website" is not a defence.
ESSENTIALS = {
    "what the product is": ("dispatch",),
    "setting up a truck's group": ("Change group info", "Pin messages"),
    "the trial and what it costs": ("7-day", "trial", "payment method"),
    "who pays for the shared plan": ("Who pays", "one plan"),
}

# Answered in full on the site. The bot is allowed to be silent on these -
# it links instead - but the site is not.
SITE_ONLY = {
    "reading the group description": ("readbio",),
    "the company logo": ("logo",),
    "billing history": ("history",),
    "notifications": ("Settings", "Telegram", "email"),
    "gmail": ("OAuth",),
    "gps": ("Samsara",),
    "what the ai does": ("Gemini",),
    "dispatchers": ("dispatcher",),
}


@pytest.mark.parametrize("subject,needles", sorted(ESSENTIALS.items()))
def test_the_bot_answers_the_essentials(subject, needles):
    for needle in needles:
        assert needle.lower() in BOT_FAQ.lower(), f"{subject}: {needle!r}"


@pytest.mark.parametrize(
    "subject,needles", sorted({**ESSENTIALS, **SITE_ONLY}.items())
)
def test_the_site_answers_everything(subject, needles):
    for needle in needles:
        assert needle.lower() in PAGE.lower(), f"{subject}: {needle!r}"


def test_the_bot_sends_people_to_the_full_version():
    """The whole basis for the bot's copy being short. Without this line it
    is not a summary, it is just an FAQ missing most of its answers."""
    assert "/pages/faq" in BOT_FAQ or "FAQ page on the dashboard" in BOT_FAQ


def test_the_bot_points_at_the_full_command_list():
    """The FAQ is a summary. Whoever read it and still has a question is one
    tap from the reference, which is the thing that is actually complete."""
    assert "/commands" in BOT_FAQ


def test_the_bot_faq_is_one_message():
    """Not a rule, an observation worth keeping: it fits comfortably now, and
    if a future edit pushes it past the limit again that is a sign it has
    stopped being the short version rather than a reason to split it."""
    import bot

    assert len(bot.split_for_telegram(bot.FAQ_TEXT)) == 1, (
        f"the bot FAQ is {len(bot.FAQ_TEXT)} characters - move an answer to the site"
    )


def test_the_site_faq_questions_are_all_reachable():
    """Every question carries an id so support can link to one answer rather
    than to the top of the page. A duplicate id would make one of them
    unreachable."""
    ids = re.findall(r"id: '([a-z0-9-]+)'", PAGE)
    assert len(ids) >= 8
    assert len(ids) == len(set(ids)), sorted(ids)


def test_the_site_faq_is_closed_by_default():
    """The point of grouping and collapsing was to get every question into
    view at once. An entry shipped with `open` on it quietly undoes that for
    everybody."""
    assert "<details className=\"faq-item card\"" in PAGE
    assert " open" not in PAGE.split("<details")[1].split(">")[0]
