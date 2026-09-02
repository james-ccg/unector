"""The house rules for user-facing error text, enforced.

Drawn from the guidance these are all built on - Nielsen Norman Group's
error-message guidelines, Google's technical-writing course, the Microsoft
Writing Style Guide, and the GOV.UK Design System - which agree on more
than they differ:

  1. Say what went wrong, specifically. "An error occurred" tells nobody
     anything (NN/g: "concise and precise description").
  2. Say what to do next. Naming the problem without a way forward leaves
     the reader stuck (NN/g: "offer constructive advice").
  3. Do not blame the reader. Avoid "invalid", "illegal", "failed" - the
     system adapts, it does not accuse (NN/g: "positive tone without
     blame").
  4. Plain language, no internal jargon. Nobody outside this repository
     knows what a CSRF token is.
  5. One verb for one meaning. Don't alternate between "Failed to",
     "Could not" and "Couldn't" for the same idea (Google: consistent
     terminology).
  6. Contractions, and no filler. Microsoft reserves "sorry" for serious
     problems and "please" for genuinely inconvenient asks; "Please try
     again" tacked onto everything is neither.

This project adds a seventh of its own: the status code travels with the
message, appended by the frontend's ApiError, so someone reporting a
problem can say which one they hit. That is why the text itself never
needs to carry a number.

Only the mechanical rules can be tested. The rest is review.
"""
import re
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = ROOT / "miniapp" / "api.py"
FRONTEND = ROOT / "frontend" / "src"

# Every user-facing string raised from the API.
MESSAGES = sorted(set(
    re.findall(
        r'HTTPException\(\s*\d{3}\s*,\s*(?:detail=)?"([^"]{4,})"', API.read_text(encoding="utf-8")
    )
))

# And the frontend's own, which a reader cannot tell apart from the
# backend's - they land in the same banner. Two shapes carry them: the
# fallback passed to errorMessage(), and the messages api.ts substitutes
# per status code.
# A double-quoted string may hold an apostrophe and a single-quoted one may
# hold a quote, so each quote style is matched on its own terms - a single
# character class stops at the first contraction and reports "Couldn".
_FRONTEND_PATTERNS = [
    r'errorMessage\(\s*err\s*,\s*"([^"]{4,})"',
    r"errorMessage\(\s*err\s*,\s*'([^']{4,})'",
    r'errorMsg = (?:\(body\.detail as string\) \|\| )?"([^"]{4,})"',
    r"errorMsg = (?:\(body\.detail as string\) \|\| )?'([^']{4,})'",
]
FRONTEND_MESSAGES = sorted({
    m
    for path in FRONTEND.rglob("*.ts*")
    for pattern in _FRONTEND_PATTERNS
    for m in re.findall(pattern, path.read_text(encoding="utf-8"))
})

BANNED = [
    (r"\bfailed\b|\bfailure\b", 'says "failed" - name what happened instead'),
    (r"\binvalid\b|\billegal\b", 'says "invalid" - blames the reader; describe what is expected'),
    (r"\bsomething went wrong\b", "too vague to act on"),
    (r"\ban error occurred\b", "too vague to act on"),
    (r"\boops\b", "not a description"),
    (r"\bsorry\b", 'reserved for serious problems - "sorry" for a typo reads as filler'),
    (r"\bplease try again\b", '"please" as filler - "Try again in a moment" says the same thing'),
    (r"\bcould not\b", 'use the contraction "couldn\'t", as the rest of the project does'),
]


def test_there_are_messages_to_check():
    """Guards the regex above: a refactor that changes how errors are
    raised would otherwise make this whole file pass by finding nothing."""
    assert len(MESSAGES) > 50, f"only found {len(MESSAGES)} - has the pattern gone stale?"


@pytest.mark.parametrize("message", MESSAGES)
def test_message_avoids_banned_wording(message):
    for pattern, why in BANNED:
        assert not re.search(pattern, message, re.I), f'"{message}" - {why}'


@pytest.mark.parametrize("message", MESSAGES)
def test_message_reads_as_a_sentence(message):
    """Starts like a sentence and ends like one. Fragments read as debug
    output, and this text is shown to customers."""
    assert message[0].isupper() or message[0] in "'\"", f'"{message}" - starts lowercase'
    assert message.rstrip()[-1] in ".!?", f'"{message}" - no closing punctuation'


def test_the_frontend_has_messages_to_check():
    assert len(FRONTEND_MESSAGES) > 15, f"only found {len(FRONTEND_MESSAGES)}"


@pytest.mark.parametrize("message", FRONTEND_MESSAGES)
def test_frontend_message_avoids_banned_wording(message):
    """The reader cannot tell which side of the wire a message came from,
    so both sides answer to the same rules."""
    for pattern, why in BANNED:
        assert not re.search(pattern, message, re.I), f'"{message}" - {why}'
