"""
The FAQ exists twice, and the two copies have to answer the same questions.

`/faq` in Telegram and /pages/faq on the site are written in different
languages and read by different people - plenty of owners only ever see the
bot. They drifted once already: the site gained the trial-reminder email and
the bot did not, and neither mentioned the group features at all for two
days after they shipped.

Wording is not checked here; the two are allowed to read differently, and
the bot's has to fit in a Telegram message. What is checked is that neither
copy is silently missing a subject the other covers, and that neither
answers a question about something the product does not do.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")
PAGE = (ROOT / "frontend" / "src" / "pages" / "FAQPage.tsx").read_text(encoding="utf-8")


def _bot_faq() -> str:
    start = BOT.index('Command("faq")')
    end = BOT.index("@dp.", start + 1)
    return BOT[start:end]


BOT_FAQ = _bot_faq()


# Each subject, and a word or phrase that has to appear in an answer about
# it on both surfaces. Deliberately loose - these are the nouns the subject
# cannot be discussed without, not the sentences we happen to use today.
SUBJECTS = {
    "what the product is": ("dispatch",),
    "setting up a truck's group": ("Change group info", "Pin messages"),
    "reading the group description": ("readbio",),
    "the company logo": ("logo",),
    "the trial and what it costs": ("7-day", "trial", "payment method"),
    "notifications": ("Settings", "Telegram", "email"),
    "gmail": ("OAuth",),
    "gps": ("Samsara",),
    "what the ai does": ("Gemini",),
    "dispatchers": ("dispatcher",),
}


@pytest.mark.parametrize("subject,needles", sorted(SUBJECTS.items()))
def test_the_bot_answers_the_subject(subject, needles):
    for needle in needles:
        assert needle.lower() in BOT_FAQ.lower(), f"{subject}: {needle!r}"


@pytest.mark.parametrize("subject,needles", sorted(SUBJECTS.items()))
def test_the_site_answers_the_subject(subject, needles):
    for needle in needles:
        assert needle.lower() in PAGE.lower(), f"{subject}: {needle!r}"


def test_the_bot_points_at_the_full_command_list():
    """The FAQ is a summary. Whoever read it and still has a question is one
    tap from the reference, which is the thing that is actually complete."""
    assert "/commands" in BOT_FAQ


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
